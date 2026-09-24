"""Wiring: database, browser worker, hoard_link, ingest runner, and every
domain module (library, tokens, references, lint, critique) behind one
object the API routers and agent tools share.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from . import SERVICE, __version__
from . import critique as critique_mod
from . import library as library_mod
from . import lint as lint_mod
from . import references as references_mod
from . import tokens as tokens_mod
from .browser import BrowserWorker
from .config import Config
from .db import Database
from .hoard_link.config import LinkConfig
from .ingest.git import git_available
from .ingest.runner import IngestRunner, ingest_source

log = logging.getLogger("vitruvius")


def write_token(config: Config) -> str:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(32)
    config.token_path.write_text(token, encoding="utf-8")
    try:
        config.token_path.chmod(0o600)
    except OSError:
        pass
    return token


def write_url(config: Config) -> None:
    try:
        config.url_path.write_text(f"http://127.0.0.1:{config.port}", encoding="utf-8")
    except OSError:
        pass


def ffmpeg_available() -> bool:
    import shutil
    return shutil.which("ffmpeg") is not None


class Services:
    def __init__(self, config: Config, *, browser: Any = None, link: Any = None, clock_fn: Callable[[], float] = time.time,
                 autostart_ingest: bool = True):
        self.config = config
        self.clock = clock_fn
        self.started_at = time.time()
        config.data_dir.mkdir(parents=True, exist_ok=True)
        config.sources_dir.mkdir(parents=True, exist_ok=True)
        config.renders_dir.mkdir(parents=True, exist_ok=True)
        config.references_dir.mkdir(parents=True, exist_ok=True)
        self.token = write_token(config)
        write_url(config)
        self.db = Database(config.db_path)

        self.browser = browser or BrowserWorker(config.data_dir, timeout_s=config.render_timeout_s)

        if link is not None:
            self.link_sync = link  # test double, already "sync-shaped"
            self._link = None
        else:
            from .hoard_link.link import Link
            link_config = LinkConfig.load(config.backend_json_path if config.backend_json_path.is_file() else None,
                                          app="vitruvius")
            self._link = Link(link_config)
            self.link_sync = self._link.sync

        self._ingest_autostart = autostart_ingest
        self.ingest_runner = IngestRunner(self.db, self.config, emit=self._emit_event)

    def _emit_event(self, type_: str, data: dict[str, Any]) -> None:
        try:
            from .hoard_link import family
            family.emit(type_, data)
        except Exception:  # noqa: BLE001
            pass

    # ---------------- lifecycle ----------------
    def start(self) -> None:
        self.browser.start()
        if self._ingest_autostart:
            self.ingest_runner.start()

    def stop(self) -> None:
        self.ingest_runner.stop()
        self.browser.stop()
        if self._link is not None:
            try:
                self.link_sync.close()
            except Exception:  # noqa: BLE001
                pass
        self.db.close()

    # ---------------- sources ----------------
    def sources_list(self) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM sources ORDER BY id")
        return [self._source_dict(r) for r in rows]

    @staticmethod
    def _source_dict(r) -> dict[str, Any]:
        return {
            "id": r["id"], "kind": r["kind"], "url": r["url"], "license": r["license"], "category": r["category"],
            "tags": json.loads(r["tags"] or "[]"), "paths": json.loads(r["paths"] or "[]"),
            "structured": bool(r["structured"]), "status": r["status"], "error": r["error"], "docs": r["docs"],
            "chunks": r["chunks"], "commit": r["commit_sha"], "last_ingest_ts": r["last_ingest_ts"], "note": r["note"],
        }

    def source_add(self, *, id: str, url: str, kind: str = "git", license: str = "", category: str = "",
                   paths: Optional[list[str]] = None, tags: Optional[list[str]] = None, structured: bool = False,
                   note: str = "") -> dict[str, Any]:
        self.db.execute(
            "INSERT INTO sources(id, kind, url, license, category, tags, paths, structured, status, note) "
            "VALUES (?,?,?,?,?,?,?,?, 'idle', ?) "
            "ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, url=excluded.url, license=excluded.license, "
            "category=excluded.category, tags=excluded.tags, paths=excluded.paths, structured=excluded.structured, note=excluded.note",
            (id, kind, url, license, category, json.dumps(tags or []), json.dumps(paths or []), int(structured), note),
        )
        row = self.db.one("SELECT * FROM sources WHERE id = ?", (id,))
        return self._source_dict(row)

    def seed_sources(self, seeds: dict[str, Any]) -> int:
        count = 0
        for s in seeds.get("sources", []):
            existing = self.db.one("SELECT id FROM sources WHERE id = ?", (s["id"],))
            if existing:
                continue
            self.source_add(id=s["id"], url=s.get("url", ""), kind=s.get("kind", "git"), license=s.get("license", ""),
                            category=s.get("category", ""), paths=s.get("paths", []), tags=s.get("tags", []),
                            structured=bool(s.get("structured", False)), note=s.get("note", ""))
            count += 1
        return count

    def source_status(self, source_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM sources WHERE id = ?", (source_id,))
        if row is None:
            raise LookupError(f"Unknown source '{source_id}'.")
        return self._source_dict(row)

    def source_ingest(self, source_id: Optional[str] = None, *, all: bool = False, sync: bool = False) -> dict[str, Any]:
        if all:
            ids = [r["id"] for r in self.db.query("SELECT id FROM sources")]
        elif source_id:
            ids = [source_id]
        else:
            raise ValueError("source_ingest needs a source id or all=true")
        for sid in ids:
            if self.db.one("SELECT id FROM sources WHERE id = ?", (sid,)) is None:
                raise LookupError(f"Unknown source '{sid}'.")
            if sync:
                ingest_source(self.db, self.config, dict(self.db.one("SELECT * FROM sources WHERE id = ?", (sid,))))
            else:
                self.ingest_runner.enqueue(sid)
        return {"ok": True, "queued": ids}

    def ingest_now(self, source_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM sources WHERE id = ?", (source_id,))
        if row is None:
            raise LookupError(f"Unknown source '{source_id}'.")
        return ingest_source(self.db, self.config, dict(row))

    # ---------------- library ----------------
    def library_search(self, query: str, **kwargs) -> list[dict[str, Any]]:
        return library_mod.search(self.db, query, **kwargs)

    def library_rules(self, **kwargs) -> list[dict[str, Any]]:
        return library_mod.list_rules(self.db, **kwargs)

    def library_brief(self, **kwargs) -> dict[str, Any]:
        use_model = kwargs.pop("use_model", False)
        return library_mod.brief(self.db, use_model=use_model, link=self.link_sync if use_model else None, **kwargs)

    def catalog_styles(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM styles ORDER BY id LIMIT ?", (limit,))
        return [self._style_dict(r) for r in rows]

    @staticmethod
    def _style_dict(r) -> dict[str, Any]:
        return {"id": r["id"], "source_id": r["source_id"], "name": r["name"], "slug": r["slug"],
                "description": r["description"], "keywords": json.loads(r["keywords"] or "[]"),
                "colors": json.loads(r["colors"] or "[]"), "typography": json.loads(r["typography"] or "{}"),
                "effects": json.loads(r["effects"] or "[]"), "best_for": json.loads(r["best_for"] or "[]"),
                "avoid": json.loads(r["avoid"] or "[]"), "css_hints": r["css_hints"]}

    def catalog_palettes(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM palettes ORDER BY id LIMIT ?", (limit,))
        return [{"id": r["id"], "source_id": r["source_id"], "name": r["name"], "product_type": r["product_type"],
                "colors": json.loads(r["colors"] or "[]"), "notes": r["notes"]} for r in rows]

    def catalog_fonts(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM font_pairings ORDER BY id LIMIT ?", (limit,))
        return [{"id": r["id"], "source_id": r["source_id"], "heading": r["heading"], "body": r["body"],
                "mono": r["mono"], "category": r["category"], "mood": r["mood"],
                "google_fonts_url": r["google_fonts_url"], "notes": r["notes"]} for r in rows]

    # ---------------- renders ----------------
    def render(self, *, html: Optional[str] = None, url: Optional[str] = None, widths: Optional[list[int]] = None,
              full_page: bool = True, dark: bool = False, wait_ms: int = 800, lint: bool = True,
              record: bool = False, title: str = "") -> dict[str, Any]:
        if not html and not url:
            raise ValueError("render needs html or url")
        t0 = time.monotonic()
        render_id = uuid.uuid4().hex[:12]
        out_dir = self.config.renders_dir / render_id
        capture = self.browser.capture(html=html, url=url, widths=widths, full_page=full_page, dark=dark,
                                       wait_ms=wait_ms, record=record, out_dir=out_dir)
        ms = (time.monotonic() - t0) * 1000
        input_hash = str(hash((html or "") + (url or "")))
        kind = "url" if url else "html"

        lint_result = {"findings": [], "score": 10.0, "counts": {}}
        probe = capture.get("probe") or {}
        if lint and "error" not in capture:
            lint_result = lint_mod.run_lint(probe, html or "")

        files = capture.get("files") or []
        metrics = {
            "fonts": (probe.get("fonts") or {}), "colors": probe.get("colors") or [],
            "libs": probe.get("external_libs") or [], "dom_size": probe.get("dom_size"),
        }
        row = {
            "id": render_id, "created_ts": time.time(), "kind": kind, "input_hash": input_hash, "url": url or "",
            "title": title, "widths": widths or [390, 1024, 1440], "dark": dark, "files": files, "metrics": metrics,
            "lint": lint_result, "ms": ms,
        }
        if "error" in capture:
            row["metrics"] = {"error": capture["error"], "hint": capture.get("hint")}
        self.db.execute(
            "INSERT INTO renders(id, created_ts, kind, input_hash, url, title, widths, dark, files, metrics, lint, ms) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (row["id"], row["created_ts"], row["kind"], row["input_hash"], row["url"], row["title"],
             json.dumps(row["widths"]), int(dark), json.dumps(row["files"]), json.dumps(row["metrics"]),
             json.dumps(row["lint"]), row["ms"]),
        )
        self._emit_event("vitruvius.render.done", {"render_id": render_id, "ok": "error" not in capture})
        row["_html"] = html
        row["_probe"] = probe
        return row

    @staticmethod
    def _render_dict(r) -> dict[str, Any]:
        return {"id": r["id"], "created_ts": r["created_ts"], "kind": r["kind"], "input_hash": r["input_hash"],
               "url": r["url"], "title": r["title"], "widths": json.loads(r["widths"] or "[]"), "dark": bool(r["dark"]),
               "files": json.loads(r["files"] or "[]"), "metrics": json.loads(r["metrics"] or "{}"),
               "lint": json.loads(r["lint"] or "{}"), "ms": r["ms"]}

    def get_render(self, render_id: str) -> Optional[dict[str, Any]]:
        row = self.db.one("SELECT * FROM renders WHERE id = ?", (render_id,))
        return self._render_dict(row) if row else None

    def list_renders(self, limit: int = 30) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM renders ORDER BY created_ts DESC LIMIT ?", (limit,))
        return [self._render_dict(r) for r in rows]

    def render_file_path(self, render_id: str, name: str) -> Path:
        base = (self.config.renders_dir / render_id).resolve()
        candidate = (base / name).resolve()
        if base not in candidate.parents and candidate != base:
            raise PermissionError("path escapes the render directory")
        return candidate

    def render_compare(self, render_a: str, render_b: str, width: Optional[int] = None) -> dict[str, Any]:
        a = self.get_render(render_a)
        b = self.get_render(render_b)
        if a is None:
            raise LookupError(f"Unknown render '{render_a}'.")
        if b is None:
            raise LookupError(f"Unknown render '{render_b}'.")

        def pick(render, w):
            files = render["files"]
            if w:
                for f in files:
                    if f["width"] == w:
                        return f["path"]
            return files[0]["path"] if files else None

        path_a, path_b = pick(a, width), pick(b, width)
        if not path_a or not path_b:
            return {"diff_pct": None, "diff_image": None, "error": "no screenshot to compare"}
        try:
            from PIL import Image, ImageChops
        except Exception:  # noqa: BLE001
            return {"diff_pct": None, "diff_image": None, "error": "Pillow not available"}
        img_a = Image.open(path_a).convert("RGB")
        img_b = Image.open(path_b).convert("RGB")
        w = min(img_a.width, img_b.width)
        h = min(img_a.height, img_b.height)
        img_a = img_a.crop((0, 0, w, h))
        img_b = img_b.crop((0, 0, w, h))
        diff = ImageChops.difference(img_a, img_b)
        bbox = diff.getbbox()
        histogram = diff.convert("L").histogram()
        total = w * h
        differing = sum(histogram[16:])  # pixels with any channel difference > ~threshold
        pct = round(100.0 * differing / total, 2) if total else 0.0
        out_path = self.config.renders_dir / f"diff-{render_a}-{render_b}.png"
        diff.save(out_path)
        return {"diff_pct": pct, "diff_image": str(out_path), "width": w, "height": h, "changed_bbox": bbox}

    def lint_html(self, *, html: Optional[str] = None, url: Optional[str] = None, render_id: Optional[str] = None) -> dict[str, Any]:
        if render_id:
            render = self.get_render(render_id)
            if render is None:
                raise LookupError(f"Unknown render '{render_id}'.")
            probe = render["metrics"]
            return lint_mod.run_lint(probe, html or "")
        if html is None and url is None:
            raise ValueError("lint needs html, url or render_id")
        capture = self.browser.capture(html=html, url=url, widths=[1024], full_page=False,
                                       out_dir=self.config.renders_dir / ("lint-" + uuid.uuid4().hex[:8]))
        probe = capture.get("probe") or {}
        return lint_mod.run_lint(probe, html or "")

    def critique_render(self, render_id: str, *, focus: Optional[str] = None, use_vision: bool = True) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM renders WHERE id = ?", (render_id,))
        if row is None:
            raise LookupError(f"Unknown render '{render_id}'.")
        render = self._render_dict(row)
        probe = render["metrics"] if "error" not in render["metrics"] else {}
        html = ""
        images: list[bytes] = []
        if use_vision:
            for f in render["files"]:
                try:
                    images.append(Path(f["path"]).read_bytes())
                except OSError:
                    continue
        result = critique_mod.critique(probe=probe, html=html, focus=focus, images=images or None,
                                       link=self.link_sync if use_vision else None, use_vision=use_vision)
        self.db.execute(
            "INSERT INTO critiques(render_id, created_ts, focus, score, heuristic_score, vision_model, findings, summary, ms) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (render_id, time.time(), focus or "", result["score"], result["heuristic_score"], result["vision_model"],
             json.dumps(result["findings"]), result["summary"], result["ms"]),
        )
        self._emit_event("vitruvius.critique.done", {"render_id": render_id, "score": result["score"]})
        return result

    # ---------------- tokens ----------------
    def tokens_generate(self, brief: dict[str, Any]) -> dict[str, Any]:
        tokens_id = uuid.uuid4().hex[:12]
        tokens = tokens_mod.generate(brief)
        css = tokens_mod.to_css(tokens)
        tailwind = tokens_mod.to_tailwind(tokens)
        self.db.execute(
            "INSERT INTO design_systems(id, name, created_ts, brief, tokens, css, tailwind) VALUES (?,?,?,?,?,?,?)",
            (tokens_id, brief.get("name") or tokens_id, time.time(), json.dumps(brief), json.dumps(tokens), css, tailwind),
        )
        self._emit_event("vitruvius.tokens.created", {"id": tokens_id})
        return self.tokens_get(tokens_id)

    @staticmethod
    def _tokens_dict(r) -> dict[str, Any]:
        return {"id": r["id"], "name": r["name"], "created_ts": r["created_ts"], "brief": json.loads(r["brief"] or "{}"),
               "tokens": json.loads(r["tokens"] or "{}"), "css": r["css"], "tailwind": r["tailwind"],
               "preview_render_id": r["preview_render_id"]}

    def tokens_get(self, tokens_id: str) -> Optional[dict[str, Any]]:
        row = self.db.one("SELECT * FROM design_systems WHERE id = ?", (tokens_id,))
        return self._tokens_dict(row) if row else None

    def tokens_list(self, limit: int = 30) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM design_systems ORDER BY created_ts DESC LIMIT ?", (limit,))
        return [self._tokens_dict(r) for r in rows]

    def tokens_delete(self, tokens_id: str) -> bool:
        cur = self.db.execute("DELETE FROM design_systems WHERE id = ?", (tokens_id,))
        return cur.rowcount > 0

    def tokens_export(self, tokens_id: str, fmt: str) -> Any:
        row = self.tokens_get(tokens_id)
        if row is None:
            raise LookupError(f"Unknown design system '{tokens_id}'.")
        if fmt == "css":
            return row["css"]
        if fmt == "tailwind":
            return row["tailwind"]
        if fmt == "w3c":
            return tokens_mod.to_w3c(row["tokens"])
        if fmt == "json":
            return tokens_mod.to_flat(row["tokens"])
        raise ValueError(f"unknown export format '{fmt}'")

    def tokens_playground_html(self, tokens_id: str, dark: bool = False) -> str:
        row = self.tokens_get(tokens_id)
        if row is None:
            raise LookupError(f"Unknown design system '{tokens_id}'.")
        return tokens_mod.playground_html(row["tokens"], dark=dark)

    def tokens_preview(self, tokens_id: str, dark: bool = False) -> dict[str, Any]:
        html = self.tokens_playground_html(tokens_id, dark=dark)
        render = self.render(html=html, widths=[390, 1024, 1440], full_page=True, dark=dark, title=f"tokens:{tokens_id}")
        self.db.execute("UPDATE design_systems SET preview_render_id = ? WHERE id = ?", (render["id"], tokens_id))
        return render

    # ---------------- references ----------------
    def reference_add(self, **kwargs) -> dict[str, Any]:
        link = kwargs.pop("link", None)
        analyze = kwargs.get("analyze", True)
        return references_mod.add(self.db, self.browser, self.config, link=self.link_sync if analyze else None, **kwargs)

    def reference_search(self, **kwargs) -> list[dict[str, Any]]:
        return references_mod.search(self.db, **kwargs)

    def reference_get(self, ref_id: str) -> Optional[dict[str, Any]]:
        return references_mod.get(self.db, ref_id)

    def reference_delete(self, ref_id: str) -> bool:
        return references_mod.delete(self.db, ref_id)

    def reference_similar(self, ref_id: str, limit: int = 6) -> list[dict[str, Any]]:
        return references_mod.similar(self.db, ref_id, limit=limit)

    def reference_file_path(self, ref_id: str, name: str) -> Path:
        base = (self.config.references_dir / ref_id).resolve()
        candidate = (base / name).resolve()
        if base not in candidate.parents and candidate != base:
            raise PermissionError("path escapes the reference directory")
        return candidate

    def import_demos(self, source_id: str) -> dict[str, Any]:
        return references_mod.import_demos(self.db, self.browser, self.config, source_id, link=self.link_sync)

    # ---------------- settings ----------------
    def get_settings(self) -> dict[str, Any]:
        backend = {}
        if self.config.backend_json_path.is_file():
            try:
                backend = json.loads(self.config.backend_json_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                backend = {}
        return {
            "backend": backend, "vision_enabled": self.db.get_setting("vision_enabled", "1") == "1",
            "widths": json.loads(self.db.get_setting("widths", "[390, 1024, 1440]")),
            "video_enabled": self.db.get_setting("video_enabled", "1") == "1",
            "language": self.db.get_setting("language", "en"),
        }

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        if "backend" in patch and patch["backend"] is not None:
            self.config.backend_json_path.write_text(json.dumps(patch["backend"], indent=2), encoding="utf-8")
        if "vision_enabled" in patch:
            self.db.set_setting("vision_enabled", "1" if patch["vision_enabled"] else "0")
        if "widths" in patch and patch["widths"]:
            self.db.set_setting("widths", json.dumps(patch["widths"]))
        if "video_enabled" in patch:
            self.db.set_setting("video_enabled", "1" if patch["video_enabled"] else "0")
        if "language" in patch and patch["language"] in ("en", "es"):
            self.db.set_setting("language", patch["language"])
        return self.get_settings()

    # ---------------- status ----------------
    def status(self) -> dict[str, Any]:
        counts = {
            "sources": self.db.one("SELECT COUNT(*) AS n FROM sources")["n"],
            "documents": self.db.one("SELECT COUNT(*) AS n FROM documents")["n"],
            "chunks": self.db.one("SELECT COUNT(*) AS n FROM chunks")["n"],
            "styles": self.db.one("SELECT COUNT(*) AS n FROM styles")["n"],
            "palettes": self.db.one("SELECT COUNT(*) AS n FROM palettes")["n"],
            "font_pairings": self.db.one("SELECT COUNT(*) AS n FROM font_pairings")["n"],
            "rules": self.db.one("SELECT COUNT(*) AS n FROM rules")["n"],
            "renders": self.db.one("SELECT COUNT(*) AS n FROM renders")["n"],
            "design_systems": self.db.one("SELECT COUNT(*) AS n FROM design_systems")["n"],
            "references": self.db.one("SELECT COUNT(*) AS n FROM references_t")["n"],
        }
        browser_status = self.browser.status() if hasattr(self.browser, "status") else {"ok": True}
        try:
            link_status = self.link_sync.status()
        except Exception as error:  # noqa: BLE001
            link_status = {"error": str(error)}
        return {
            "service": SERVICE, "version": __version__, "data_dir": str(self.config.data_dir),
            "started_at": self.started_at, "now": self.clock(), "browser": browser_status,
            "ffmpeg": ffmpeg_available(), "git": git_available(), "counts": counts, "models": link_status,
        }
