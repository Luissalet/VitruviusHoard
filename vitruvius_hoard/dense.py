"""Multilingual dense vectors over the library, fused with FTS5 by reciprocal rank.

The criterion in the library is written in English; people ask in Spanish
("¿cómo hago que los botones parezcan pulsables?"). bm25 cannot bridge that,
a multilingual sentence model can. Vectors are keyed by the SHA-1 of the chunk
text and the model name, so re-ingesting a source only embeds what changed.

- `Embedder` backends: family (Borges's Hoard through the hub, `hoard_link.fam_embed`: the one multilingual model the family keeps
  loaded), fastembed (ONNX, CPU, in this process, downloaded on first use: the offline fallback when Borges is not running),
  fake (tests), none (dense search off). Vectors of two models are never mixed: they are stored per model name.
- `DenseIndex.build()` embeds pending chunks in batches (background thread
  via `start_build`), reporting progress.
- `DenseIndex.query()` loads one float32 matrix (cached until the next build
  or ingest) and returns the nearest chunk ids by cosine (`hoard_link.docs.vecmath.topk`); the fusion with keywords is
  `hoard_link.docs.vecmath.rrf`.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

try:  # numpy arrives with fastembed; without it the app still runs, BM25 only.
    import numpy as np
except ImportError:  # pragma: no cover - exercised by test_dense via monkeypatch
    np = None  # type: ignore[assignment]

from .db import Database
from .hoard_link import fam_embed
from .hoard_link.docs import vecmath

log = logging.getLogger("vitruvius.dense")

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
FAKE_DIM = 512
HUB_PROBE_S = 30.0  # how long "is Borges there, and which model is it" is remembered


def text_hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()


class Embedder:
    name = "none"
    model = ""
    dim = 0

    def available(self) -> bool:
        """Can this backend embed at all (library installed / model obtainable)?"""
        return False

    def ready(self) -> bool:
        return False

    def ensure_loaded(self) -> bool:
        return False

    def embed(self, texts: list[str]) -> np.ndarray:  # pragma: no cover - abstract
        raise NotImplementedError

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed([text])[0]

    def status(self) -> dict[str, Any]:
        return {"backend": self.name, "model": self.model, "state": "disabled", "dim": self.dim, "error": None}


class NoneEmbedder(Embedder):
    def status(self) -> dict[str, Any]:
        missing = "numpy is not installed: pip install -r requirements.txt" if np is None else None
        return {**super().status(), "error": missing}


class FakeEmbedder(Embedder):
    """Bag-of-words hashing with a tiny ES→EN glossary, so tests can check cross-language fusion."""

    name = "fake"
    model = "fake-hash"
    dim = FAKE_DIM
    GLOSSARY = {"botones": "button", "boton": "button", "botón": "button", "pulsables": "clickable",
                "contraste": "contrast", "animacion": "animation", "animación": "animation"}

    def available(self) -> bool:
        return True

    def ready(self) -> bool:
        return True

    def ensure_loaded(self) -> bool:
        return True

    def _vector(self, text: str) -> np.ndarray:
        vec = np.zeros(FAKE_DIM, dtype=np.float32)
        for word in text.lower().split():
            word = self.GLOSSARY.get(word.strip("¿?¡!.,"), word.strip("¿?¡!.,"))
            digest = hashlib.md5(word.encode("utf-8")).digest()
            vec[int.from_bytes(digest[:2], "little") % FAKE_DIM] += 1.0
        norm = float(np.linalg.norm(vec))
        return vec / norm if norm else vec

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, FAKE_DIM), dtype=np.float32)
        return np.stack([self._vector(t) for t in texts])

    def status(self) -> dict[str, Any]:
        return {**super().status(), "state": "ready"}


class FastembedEmbedder(Embedder):
    """ONNX sentence model through fastembed; CPU by default, loaded lazily."""

    name = "fastembed"

    def __init__(self, model: str, cache_dir: Path):
        self.model = model
        self.cache_dir = cache_dir
        self._model = None
        self._lock = threading.Lock()
        self._state = "not_loaded"
        self._error: Optional[str] = None
        self._load_seconds: Optional[float] = None

    def available(self) -> bool:
        if np is None:
            return False
        try:
            import importlib.util

            return importlib.util.find_spec("fastembed") is not None
        except Exception:  # noqa: BLE001
            return False

    def cached(self) -> bool:
        return any(self.cache_dir.glob("models--*/blobs/*")) or any(self.cache_dir.glob("**/model*.onnx"))

    def ready(self) -> bool:
        return self._model is not None

    def ensure_loaded(self) -> bool:
        if self._model is not None:
            return True
        with self._lock:
            if self._model is not None:
                return True
            if not self.available():
                self._state, self._error = "error", "fastembed is not installed (pip install fastembed)"
                return False
            self._state = "loading" if self.cached() else "downloading"
            started = time.time()
            try:
                from fastembed import TextEmbedding

                self.cache_dir.mkdir(parents=True, exist_ok=True)
                model = TextEmbedding(self.model, cache_dir=str(self.cache_dir))
                probe = next(iter(model.embed(["hola"])))
                self.dim = int(len(probe))
                self._model = model
                self._state = "ready"
                self._error = None
                self._load_seconds = round(time.time() - started, 1)
                return True
            except Exception as error:  # noqa: BLE001 - download failure, missing wheel...
                self._state = "error"
                self._error = f"{type(error).__name__}: {error}"
                log.warning("embedding model unavailable: %s", self._error)
                return False

    @staticmethod
    def _normalise(matrix: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (matrix / norms).astype(np.float32)

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        if not self.ensure_loaded():
            raise RuntimeError(self._error or "embedding model not loaded")
        return self._normalise(np.asarray(list(self._model.embed(texts, batch_size=32)), dtype=np.float32))

    def embed_query(self, text: str) -> np.ndarray:
        if not self.ensure_loaded():
            raise RuntimeError(self._error or "embedding model not loaded")
        return self._normalise(np.asarray(list(self._model.query_embed(text)), dtype=np.float32))[0]

    def status(self) -> dict[str, Any]:
        return {"backend": self.name, "model": self.model, "state": self._state, "dim": self.dim,
                "error": self._error, "load_seconds": self._load_seconds, "cache_dir": str(self.cache_dir),
                "cached": self.cached()}


def default_cache_dir(data_dir: Path) -> Path:
    """Where the in-process model is kept: `VITRUVIUS_MODELS_DIR`, else `<data>/models`."""
    explicit = os.environ.get("VITRUVIUS_MODELS_DIR")
    return Path(explicit).expanduser() if explicit else data_dir / "models"


class FamilyEmbedder(Embedder):
    """Borges's embedder through the hub, with the in-process model (`local`) as the fallback when Borges is not running.

    Which of the two answers is decided by `fam_embed` (is Borges running and is its model loaded?) and remembered for 30 seconds.
    The vectors of the two models are different spaces, so `model` / `dim` always describe the one in use, the index keeps its
    vectors per model name, and a build that loses its model half way stops with an error instead of mixing two spaces."""

    name = "family"

    def __init__(self, local: Optional[Embedder] = None):
        self.local = local
        self._probe: Optional[tuple[float, Optional[dict[str, Any]]]] = None
        self._pinned: Optional[str] = None
        self._error: Optional[str] = None

    # -- who answers ---------------------------------------------------------
    def _hub(self) -> Optional[dict[str, Any]]:
        """Borges's `embed_status` while it is running and ready, else None (cached)."""
        now = time.monotonic()
        if self._probe is not None and now - self._probe[0] < HUB_PROBE_S:
            return self._probe[1]
        info: Optional[dict[str, Any]] = None
        try:
            if fam_embed.available():
                got = fam_embed.status(timeout_s=10.0)
                if got.get("ok") and got.get("ready") and got.get("model") and int(got.get("dim") or 0) > 0:
                    info = got
                else:
                    self._error = str(got.get("error") or got.get("state") or "Borges's embedder is not ready")
        except Exception as error:  # noqa: BLE001 - never raises into a search
            self._error = f"{type(error).__name__}: {error}"
        self._probe = (now, info)
        return info

    def forget(self) -> None:
        self._probe = None

    def via_hub(self) -> bool:
        return self._hub() is not None

    def _active(self) -> Optional[Embedder]:
        return self if self.via_hub() else self.local

    # -- the Embedder interface ------------------------------------------------
    @property
    def model(self) -> str:  # type: ignore[override]
        hub = self._hub()
        if hub is not None:
            return str(hub["model"])
        return self.local.model if self.local else ""

    @property
    def dim(self) -> int:  # type: ignore[override]
        hub = self._hub()
        if hub is not None:
            return int(hub["dim"])
        return self.local.dim if self.local else 0

    def available(self) -> bool:
        return self.via_hub() or bool(self.local and self.local.available())

    def ready(self) -> bool:
        return self.via_hub() or bool(self.local and self.local.ready())

    def cached(self) -> bool:
        """The model is at hand without a download."""
        return self.via_hub() or bool(self.local and getattr(self.local, "cached", lambda: False)())

    def ensure_loaded(self) -> bool:
        if self.via_hub():
            self._pinned = self.model
            return True
        self._pinned = None
        return bool(self.local and self.local.ensure_loaded())

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        if not self.via_hub():
            if self.local is None:
                raise RuntimeError(self._error or "Borges's embedder is not running")
            return self.local.embed(texts)
        got = fam_embed.embed_texts(texts, kind="document", local_fallback=False)
        if not got.get("ok"):
            self.forget()
            raise RuntimeError(f"Borges could not embed the texts: {got.get('error')}")
        if self._pinned and got.get("model") != self._pinned:
            self.forget()
            raise RuntimeError(f"the family embedding model changed during the build ({self._pinned!r} -> {got.get('model')!r}); build again")
        return np.asarray(got["vectors"], dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        if not self.via_hub():
            if self.local is None:
                raise RuntimeError(self._error or "Borges's embedder is not running")
            return self.local.embed_query(text)
        got = fam_embed.embed_query(text, local_fallback=False)
        if not got.get("ok"):
            self.forget()
            raise RuntimeError(f"Borges could not embed the query: {got.get('error')}")
        return np.asarray(got["vector"], dtype=np.float32)

    def status(self) -> dict[str, Any]:
        hub = self._hub()
        if hub is not None:
            return {"backend": self.name, "model": str(hub["model"]), "state": "ready", "dim": int(hub["dim"]), "error": None,
                    "via": "borges", "cached": True}
        base = self.local.status() if self.local else {"backend": self.name, "model": "", "state": "disabled", "dim": 0, "error": None}
        return {**base, "via": "local", "hub": self._error or "Borges's Hoard is not running"}


def make_embedder(backend: str, model: str, cache_dir: Path) -> Embedder:
    """`auto` / `fastembed`: Borges through the hub, the in-process model when it is not there; `family`: Borges only;
    `local`: the in-process model only; `fake` and `none` as named."""
    if np is None:
        return NoneEmbedder()
    if backend == "fake":
        return FakeEmbedder()
    if backend == "none":
        return NoneEmbedder()
    if backend == "local":
        return FastembedEmbedder(model, cache_dir)
    if backend == "family":
        return FamilyEmbedder(None)
    return FamilyEmbedder(FastembedEmbedder(model, cache_dir))


class DenseIndex:
    def __init__(self, db: Database, embedder: Embedder, emit: Optional[Callable[[str, dict], None]] = None):
        self.db = db
        self.embedder = embedder
        self.emit = emit or (lambda *_: None)
        self._matrix: Optional[np.ndarray] = None
        self._ids: Optional[np.ndarray] = None
        self._matrix_key: Optional[tuple] = None
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self.progress: dict[str, Any] = {"state": "idle", "done": 0, "total": 0, "error": None, "seconds": None}

    # -- bookkeeping ---------------------------------------------------------
    def _model_key(self) -> str:
        return self.embedder.model or self.embedder.name

    def counts(self) -> dict[str, int]:
        chunks = self.db.one("SELECT COUNT(*) AS n FROM chunks")["n"]
        vectors = self.db.one("SELECT COUNT(*) AS n FROM vectors WHERE model = ?", (self._model_key(),))["n"]
        return {"chunks": chunks, "vectors": vectors}

    def _pending(self) -> list[tuple[str, str]]:
        """(hash, text) of chunk texts with no vector for this model, deduplicated."""
        have = {r["hash"] for r in self.db.query("SELECT hash FROM vectors WHERE model = ?", (self._model_key(),))}
        out: dict[str, str] = {}
        for r in self.db.query("SELECT heading, text FROM chunks"):
            body = _embed_text(r["heading"], r["text"])
            h = text_hash(body)
            if h not in have and h not in out:
                out[h] = body
        return list(out.items())

    def status(self) -> dict[str, Any]:
        counts = self.counts()
        return {**self.embedder.status(), **counts, "build": dict(self.progress),
                "active": self.usable()}

    def usable(self) -> bool:
        """Vectors exist for this model and the embedder can embed a query."""
        if self.embedder.name == "none":
            return False
        row = self.db.one("SELECT COUNT(*) AS n FROM vectors WHERE model = ?", (self._model_key(),))
        return bool(row and row["n"]) and self.embedder.available()

    def invalidate(self) -> None:
        with self._lock:
            self._matrix = None
            self._ids = None
            self._matrix_key = None

    # -- build ---------------------------------------------------------------
    def build(self, batch: int = 64, max_items: Optional[int] = None) -> dict[str, Any]:
        if not self.embedder.ensure_loaded():
            self.progress = {"state": "error", "done": 0, "total": 0, "error": self.embedder.status().get("error"), "seconds": None}
            return dict(self.progress)
        pending = self._pending()
        if max_items is not None:
            pending = pending[:max_items]
        started = time.time()
        self.progress = {"state": "building", "done": 0, "total": len(pending), "error": None, "seconds": None}
        model = self._model_key()
        for i in range(0, len(pending), batch):
            part = pending[i:i + batch]
            vecs = self.embedder.embed([t for _, t in part])
            with self.db.transaction() as conn:
                for (h, _), v in zip(part, vecs):
                    conn.execute("INSERT OR REPLACE INTO vectors(hash, model, dim, vec) VALUES (?,?,?,?)",
                                 (h, model, int(v.shape[0]), v.astype(np.float32).tobytes()))
            self.progress["done"] = i + len(part)
        self.progress.update({"state": "ready", "seconds": round(time.time() - started, 1)})
        self.invalidate()
        self.emit("vitruvius.embeddings.built", {"model": model, "added": len(pending)})
        return dict(self.progress)

    def start_build(self) -> dict[str, Any]:
        if self._thread is not None and self._thread.is_alive():
            return {"started": False, "reason": "already building", **self.progress}

        def run() -> None:
            try:
                self.build()
            except Exception as error:  # noqa: BLE001
                self.progress = {**self.progress, "state": "error", "error": f"{type(error).__name__}: {error}"}
                log.exception("embedding build failed")

        self._thread = threading.Thread(target=run, name="vitruvius-embed", daemon=True)
        self.progress = {"state": "queued", "done": 0, "total": 0, "error": None, "seconds": None}
        self._thread.start()
        return {"started": True, **self.progress}

    # -- query ---------------------------------------------------------------
    def _load_matrix(self) -> tuple[np.ndarray, np.ndarray]:
        key = (self.db.one("SELECT COUNT(*) AS n, MAX(id) AS m FROM chunks")["m"],
               self.db.one("SELECT COUNT(*) AS n FROM vectors WHERE model = ?", (self._model_key(),))["n"])
        with self._lock:
            if self._matrix is not None and self._matrix_key == key:
                return self._ids, self._matrix
            vec_by_hash = {r["hash"]: r["vec"] for r in self.db.query(
                "SELECT hash, vec FROM vectors WHERE model = ?", (self._model_key(),))}
            ids: list[int] = []
            rows: list[np.ndarray] = []
            for r in self.db.query("SELECT id, heading, text FROM chunks"):
                blob = vec_by_hash.get(text_hash(_embed_text(r["heading"], r["text"])))
                if blob is not None:
                    ids.append(int(r["id"]))
                    rows.append(np.frombuffer(blob, dtype=np.float32))
            self._ids = np.asarray(ids, dtype=np.int64)
            self._matrix = np.vstack(rows) if rows else np.zeros((0, 1), dtype=np.float32)
            self._matrix_key = key
            return self._ids, self._matrix

    def query(self, text: str, k: int = 50) -> list[tuple[int, float]]:
        if not self.usable():
            return []
        ids, matrix = self._load_matrix()
        if matrix.shape[0] == 0:
            return []
        q = self.embedder.embed_query(text)
        if q.shape[0] != matrix.shape[1]:
            return []
        top = vecmath.topk(matrix, q, k, min_score=-1.0, normalized=True)
        return [(int(ids[i]), score) for i, score in top]


def _embed_text(heading: str, text: str) -> str:
    """What a chunk is embedded as: its breadcrumb heading plus the first ~1500 characters."""
    head = (heading or "").strip()
    body = (text or "").strip()[:1500]
    return f"{head}\n{body}" if head else body
