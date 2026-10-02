"""Dense vectors from Borges's Hoard through the hub (`hoard_link.fam_embed`), with the in-process model as the offline fallback."""
import numpy as np
import pytest
from test_dense import seed

from vitruvius_hoard import dense as D
from vitruvius_hoard import library
from vitruvius_hoard.db import Database
from vitruvius_hoard.dense import DenseIndex, FakeEmbedder, FamilyEmbedder


class FakeHub:
    """Stands in for `fam_embed`: Borges answers with `model`, using the fake bag-of-words vectors."""

    def __init__(self, model="hub-model-1", up=True, ready=True):
        self.model, self.up, self.ready = model, up, ready
        self.calls = []
        self.fail = None
        self.engine = FakeEmbedder()

    def available(self, timeout=1.0):
        return self.up

    def status(self, timeout_s=30.0):
        if not self.up:
            return {"ok": False, "error": "hub unreachable"}
        return {"ok": True, "model": self.model, "dim": D.FAKE_DIM, "state": "ready" if self.ready else "loading", "ready": self.ready, "via": "borges"}

    def embed_texts(self, texts, *, kind="document", normalize=True, batch=64, timeout_s=120.0, local_fallback=True, link=None):
        self.calls.append(("texts", kind, len(texts), local_fallback))
        if self.fail:
            return {"ok": False, "error": self.fail, "via": "borges", "kind": "tool_error"}
        return {"ok": True, "model": self.model, "dim": D.FAKE_DIM, "vectors": self.engine.embed(list(texts)).tolist(), "via": "borges"}

    def embed_query(self, text, *, normalize=True, timeout_s=60.0, local_fallback=True, link=None):
        self.calls.append(("query", text, local_fallback))
        got = self.embed_texts([text], kind="query", local_fallback=local_fallback)
        return {"ok": True, "model": got["model"], "dim": got["dim"], "vector": got["vectors"][0], "via": "borges"} if got["ok"] else got


@pytest.fixture
def hub(monkeypatch):
    fake = FakeHub()
    for name in ("available", "status", "embed_texts", "embed_query"):
        monkeypatch.setattr(D.fam_embed, name, getattr(fake, name))
    return fake


class LocalFake(FakeEmbedder):
    model = "local-model"


def test_with_borges_up_the_index_is_built_and_searched_through_the_hub(tmp_path, hub):
    db = Database(tmp_path / "v.db")
    seed(db)
    embedder = FamilyEmbedder(LocalFake())
    index = DenseIndex(db, embedder)
    assert embedder.via_hub() and embedder.model == "hub-model-1" and index.status()["backend"] == "family"
    assert index.build()["state"] == "ready"
    assert db.one("SELECT COUNT(DISTINCT model) AS n, MIN(model) AS m FROM vectors")["m"] == "hub-model-1"
    hits = library.search(db, "¿cómo hago botones pulsables?", dense=index, limit=3)
    assert hits and hits[0]["heading"] == "Buttons" and hits[0]["match"] == "dense"
    assert ("texts", "document", 3, False) in hub.calls and any(c[0] == "query" for c in hub.calls)


def test_without_borges_the_in_process_model_answers_and_vectors_stay_apart(tmp_path, hub):
    db = Database(tmp_path / "v.db")
    seed(db)
    embedder = FamilyEmbedder(LocalFake())
    index = DenseIndex(db, embedder)
    index.build()  # through the hub
    hub.up = False
    embedder.forget()
    assert not embedder.via_hub() and embedder.model == "local-model"
    assert not index.usable()  # the hub vectors are another space: nothing is searched with them
    assert library.search(db, "contrast", dense=index)[0]["match"] == "bm25"
    index.build()
    assert index.usable() and index.status()["via"] == "local" and "hub" in index.status()
    assert db.one("SELECT COUNT(*) AS n FROM vectors")["n"] == 6  # three chunks, two models
    hub.up = True
    embedder.forget()
    assert embedder.model == "hub-model-1" and index.usable()  # back on the hub: its vectors are still there


def test_a_loading_borges_is_not_used_yet(tmp_path, hub):
    hub.ready = False
    embedder = FamilyEmbedder(LocalFake())
    assert not embedder.via_hub() and embedder.model == "local-model" and embedder.ensure_loaded()


def test_a_failing_hub_stops_the_build_instead_of_mixing_models(tmp_path, hub):
    db = Database(tmp_path / "v.db")
    seed(db)
    index = DenseIndex(db, FamilyEmbedder(LocalFake()))
    hub.fail = "model is loading"
    with pytest.raises(RuntimeError, match="Borges could not embed the texts: model is loading"):
        index.build()
    assert db.one("SELECT COUNT(*) AS n FROM vectors")["n"] == 0
    # a search never breaks because of it
    assert library.search(db, "contrast", dense=index)[0]["match"] == "bm25"


def test_a_model_change_during_a_build_is_refused(tmp_path, hub):
    embedder = FamilyEmbedder(None)
    assert embedder.ensure_loaded()
    hub.model = "hub-model-2"
    with pytest.raises(RuntimeError, match="changed during the build"):
        embedder.embed(["x"])


def test_no_borges_and_no_local_model_means_keyword_search_only(tmp_path, hub):
    hub.up = False
    db = Database(tmp_path / "v.db")
    seed(db)
    embedder = FamilyEmbedder(None)
    index = DenseIndex(db, embedder)
    assert not embedder.available() and not index.usable() and index.build()["state"] == "error"
    assert library.search(db, "contrast", dense=index)[0]["match"] == "bm25"


def test_make_embedder_backends(tmp_path):
    assert D.make_embedder("auto", D.DEFAULT_MODEL, tmp_path).name == "family"
    assert D.make_embedder("fastembed", D.DEFAULT_MODEL, tmp_path).local.name == "fastembed"
    assert D.make_embedder("family", D.DEFAULT_MODEL, tmp_path).local is None
    assert D.make_embedder("local", D.DEFAULT_MODEL, tmp_path).name == "fastembed"
    assert D.make_embedder("fake", D.DEFAULT_MODEL, tmp_path).name == "fake" and D.make_embedder("none", D.DEFAULT_MODEL, tmp_path).name == "none"


def test_the_model_folder_is_no_longer_borrowed_from_a_sibling_app(tmp_path, monkeypatch):
    monkeypatch.delenv("VITRUVIUS_MODELS_DIR", raising=False)
    sibling = tmp_path / "Borges Hoard" / "data" / "models" / "models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"
    sibling.mkdir(parents=True)
    data = tmp_path / "Vitruvius Hoard" / "data"
    data.mkdir(parents=True)
    assert D.default_cache_dir(data) == data / "models"
    monkeypatch.setenv("VITRUVIUS_MODELS_DIR", str(tmp_path / "elsewhere"))
    assert D.default_cache_dir(data) == tmp_path / "elsewhere"


def test_the_matrix_search_is_the_shared_top_k(tmp_path):
    db = Database(tmp_path / "v.db")
    seed(db)
    index = DenseIndex(db, FakeEmbedder())
    index.build()
    hits = index.query("animation", k=2)
    assert len(hits) == 2 and hits[0][1] >= hits[1][1]
    assert all(isinstance(i, int) and isinstance(s, float) for i, s in hits)
    assert hits[0][0] == db.one("SELECT id FROM chunks WHERE heading = 'Motion'")["id"]


def test_services_report_which_side_serves_the_vectors(client, hub):
    client.svc.embedder = FamilyEmbedder(LocalFake())
    client.svc.dense = DenseIndex(client.svc.db, client.svc.embedder)
    body = client.get("/api/library/embeddings").json()
    assert body["backend"] == "family" and body["via"] == "borges" and body["model"] == "hub-model-1" and body["active"] is False
