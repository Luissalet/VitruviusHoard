"""Wiring: database, browser worker, hoard_link, ingest runner, and every
domain module (library, tokens, references, lint, critique) behind one
object the API routers and agent tools share.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from . import SERVICE, __version__
from . import assay as assay_mod
from . import critique as critique_mod
from . import library as library_mod
from . import lint as lint_mod
from . import references as references_mod
from . import reference_collections, design_patterns
from . import tokens as tokens_mod
from . import kept as kept_mod
from . import themes as themes_mod
from . import waivers as waivers_mod
from .browser import BrowserWorker
from .alternatives import AlternativeStudies
from .app_projects import AppProjects
from .instruments import Instruments
from .config import Config
from .db import Database
from .hoard_link import fam_web
from .hoard_link import tokens as tokens_lib
from .hoard_link.atomic import write_json_atomic
from .hoard_link.config import LinkConfig
from .hoard_link.media import bins as media_bins
from .hoard_link.web import safety
from .rules.registry import ENGINES
from .hoard_link.tokens import read_or_create_token
from .ingest.git import git_available
from .ingest.runner import IngestRunner, ingest_source

log = logging.getLogger("vitruvius")


def write_token(config: Config) -> str:
    """The MCP token is persistent: created once, reused on every later start (`hoard_link.tokens.read_or_create_token`).

    Rotating it on each start would break a bridge (or a second, port-clashing
    instance would break the running one) the moment the file changed.
    """
    config.data_dir.mkdir(parents=True, exist_ok=True)
    return read_or_create_token(config.token_path)


def write_url(config: Config) -> None:
    try:
        tokens_lib.write_url(config.url_path, f"http://127.0.0.1:{config.port}")
    except OSError:
        pass


def ffmpeg_available() -> bool:
    return bool(media_bins.find("ffmpeg"))


class Services:
    def __init__(self, config: Config, *, browser: Any = None, link: Any = None, clock_fn: Callable[[], float] = time.time,
                 autostart_ingest: bool = False, assay_runner: Any = None):
        self.config = config
        self.assay_runner = assay_runner  # tests inject a fake `(cmd, timeout) -> (code, out, err)`
        self.clock = clock_fn
        self.started_at = time.time()
        config.data_dir.mkdir(parents=True, exist_ok=True)
        config.sources_dir.mkdir(parents=True, exist_ok=True)
        config.renders_dir.mkdir(parents=True, exist_ok=True)
        config.references_dir.mkdir(parents=True, exist_ok=True)
        self.token = write_token(config)
        write_url(config)
        self.db = Database(config.db_path)

        self.app_projects = AppProjects(config.data_dir)
        self.alternatives = AlternativeStudies(self)
        self.instruments = Instruments(self.app_projects)
        self.app_browser = browser or BrowserWorker(config.data_dir / "app-previews", timeout_s=config.render_timeout_s, profile="operator_local")
        self.browser = browser or BrowserWorker(config.data_dir, timeout_s=config.render_timeout_s, profile=config.url_profile)

        if link is not None:
            self.link_sync = link  # test double, already "sync-shaped"
            self._link = None
        else:
            from .software.global_models import GlobalLink as Link
            link_config = LinkConfig.load(config.backend_json_path if config.backend_json_path.is_file() else None,
                                          app="vitruvius")
            self._link = Link(link_config)
            self.link_sync = self._link.sync

        self._ingest_autostart = autostart_ingest and config.autostart
        self.ingest_runner = IngestRunner(self.db, self.config, emit=self._emit_event)

        from .dense import DenseIndex, default_cache_dir, make_embedder
        self.embedder = make_embedder(config.embed_backend, config.embed_model, default_cache_dir(config.data_dir))
        self.dense = DenseIndex(self.db, self.embedder, emit=self._emit_event)

    def _emit_event(self, type_: str, data: dict[str, Any]) -> None:
        if type_ == "vitruvius.source.ingested" and hasattr(self, "dense"):
            # New chunk texts: the cached matrix is stale; embed what changed when the model is at hand.
            self.dense.invalidate()
            if self.config.embed_auto and getattr(self.embedder, "cached", lambda: False)() and self.dense.usable():
                self.dense.start_build()
        try:
            from .hoard_link import family
            family.emit(type_, data)
        except Exception:  # noqa: BLE001
            pass

    # ---------------- lifecycle ----------------
    def start(self) -> None:
        if self._ingest_autostart:
            self.ingest_runner.start()

    def stop(self) -> None:
        def dense():
            if self.dense._thread is not None:
                self.dense._thread.join()
        def app_browser():
            if self.app_browser is not self.browser:
                self.app_browser.stop()
        def link():
            import asyncio
            if self._link is not None:
                asyncio.run(self._link.aclose())
        steps = (self.ingest_runner.stop, dense, self.app_projects.close,
                 self.browser.stop, app_browser, link, self.db.close)
        completed = getattr(self, '_stop_completed', 0)
        while completed < len(steps):
            steps[completed]()
            completed += 1
            self._stop_completed = completed

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
        return library_mod.search(self.db, query, dense=self.dense, **kwargs)

    def embeddings_build(self, wait: bool = False) -> dict[str, Any]:
        """Embed every chunk that has no vector yet (multilingual model, CPU)."""
        if self.config.embed_backend == "none":
            return {"started": False, "error": "dense search is off (VITRUVIUS_EMBED=none)"}
        if wait:
            return self.dense.build()
        return self.dense.start_build()

    def library_rules(self, **kwargs) -> list[dict[str, Any]]:
        return library_mod.list_rules(self.db, **kwargs)

    def library_brief(self, **kwargs) -> dict[str, Any]:
        use_model = kwargs.pop("use_model", False)
        out = library_mod.brief(self.db, use_model=use_model, link=self.link_sync if use_model else None, **kwargs)
        try:
            # the brief also deals three themes the memory of the recent builds allows (reproducible by its seed)
            prompt = " ".join(str(kwargs.get(k) or "") for k in ("subject", "vibe", "product_type")).strip()
            out["theme_deal"] = self.theme_deal(prompt=prompt, n=3)
        except Exception:  # noqa: BLE001 — the brief never fails for want of a theme
            log.warning("could not deal themes for the brief", exc_info=True)
        return out

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

    # ---------------- what the assistant may ask the browser to open ----------------
    def check_url(self, url: Optional[str]) -> None:
        """Refuse a URL that is not a public web page (localhost, the local network, a cloud metadata address, credentials in the
        URL, a scheme other than http/https). `VITRUVIUS_ALLOW_LOCAL_URLS=1` also lets local and private-network pages through."""
        if not url:
            return
        problem = safety.check_url(url, self.config.url_profile)
        if problem and not problem.startswith(safety.UNRESOLVABLE_PREFIX):
            raise ValueError(f"This URL cannot be opened: {problem}")

    # ---------------- renders ----------------
    def render(self, *, html: Optional[str] = None, url: Optional[str] = None, widths: Optional[list[int]] = None,
              full_page: bool = True, dark: bool = False, wait_ms: int = 800, lint: bool = True,
              record: bool = False, title: str = "", tokens_id: Optional[str] = None, _browser=None, _app_project=None) -> dict[str, Any]:
        if not html and not url:
            raise ValueError("render needs html or url")
        if _browser is None:
            self.check_url(url)
        t0 = time.monotonic()
        render_id = uuid.uuid4().hex[:12]
        out_dir = self.config.renders_dir / render_id
        capture = (_browser or self.browser).capture(html=html, url=url, widths=widths, full_page=full_page, dark=dark,
                                       wait_ms=wait_ms, record=record, out_dir=out_dir)
        ms = (time.monotonic() - t0) * 1000
        if html is not None:
            # Kept next to the screenshots so a later page_assay / render_compare can reopen the page.
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "source.html").write_text(html, encoding="utf-8")
            except OSError:
                pass
        input_hash = str(hash((html or "") + (url or "")))
        kind = "url" if url else "html"

        lint_result = {"findings": [], "score": 10.0, "counts": {}}
        probe = capture.get("probe") or {}
        if lint and "error" not in capture:
            lint_result = lint_mod.run_lint(probe, html or "", tokens=self._system_tokens(tokens_id))

        files = capture.get("files") or []
        metrics = {
            "fonts": (probe.get("fonts") or {}), "colors": probe.get("colors") or [],
            "libs": probe.get("external_libs") or [], "dom_size": probe.get("dom_size"),
            # the whole probe, so a later critique or lint of this render sees what the render-time lint saw
            "probe": probe,
        }
        if _app_project is not None:
            metrics["app_project"] = _app_project

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
               "files": json.loads(r["files"] or "[]"),
               "metrics": {k: v for k, v in json.loads(r["metrics"] or "{}").items() if k != "probe"},  # probe: lint only
               "lint": json.loads(r["lint"] or "{}"), "ms": r["ms"]}

    def _render_lint_inputs(self, render: dict[str, Any]) -> tuple[dict[str, Any], str]:
        """Probe and HTML to lint a stored render with: the full probe kept at render time (older renders only have the
        summary metrics) and the page's own source when it was rendered from HTML."""
        row = self.db.one("SELECT metrics FROM renders WHERE id = ?", (render["id"],))
        metrics = json.loads(row["metrics"] or "{}") if row else {}
        if "error" in metrics:
            return {}, ""
        probe = metrics.get("probe") if isinstance(metrics.get("probe"), dict) else metrics
        html = ""
        source = self.config.renders_dir / render["id"] / "source.html"
        try:
            if source.is_file():
                html = source.read_text(encoding="utf-8")
        except OSError:
            html = ""
        return probe, html

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

    def _system_tokens(self, tokens_id: Optional[str]) -> Optional[dict[str, Any]]:
        """The tokens of a stored design system, for the rules that compare a page with it (None when none is asked for)."""
        if not tokens_id:
            return None
        row = self.tokens_get(tokens_id)
        if row is None:
            raise LookupError(f"Unknown design system '{tokens_id}'.")
        return row["tokens"]

    def lint_html(self, *, html: Optional[str] = None, url: Optional[str] = None, render_id: Optional[str] = None,
                  tokens_id: Optional[str] = None, packs: Optional[list[str]] = None, engines: Optional[list[str]] = None) -> dict[str, Any]:
        tokens = self._system_tokens(tokens_id)
        engines = [e for e in (engines or []) if e] or None
        if engines and not set(engines) <= set(ENGINES):
            raise ValueError(f"engines must be among {', '.join(ENGINES)}")
        if engines == ["static"] and html is not None and not render_id and not url:
            # The static rules read the source text and its cascade: no capture, no browser.
            return lint_mod.run_lint({}, html, tokens=tokens, packs=packs, engines=engines)
        if render_id:
            render = self.get_render(render_id)
            if render is None:
                raise LookupError(f"Unknown render '{render_id}'.")
            probe, source = self._render_lint_inputs(render)
            return lint_mod.run_lint(probe, html or source, tokens=tokens, packs=packs, engines=engines)
        if html is None and url is None:
            raise ValueError("lint needs html, url or render_id")
        self.check_url(url)
        capture = self.browser.capture(html=html, url=url, widths=[390, 1440], full_page=False,
                                       out_dir=self.config.renders_dir / ("lint-" + uuid.uuid4().hex[:8]))
        probe = capture.get("probe") or {}
        return lint_mod.run_lint(probe, html or "", tokens=tokens, packs=packs, engines=engines)

    # ---------------- rules as data ----------------
    def rules_list(self, **filters: Any) -> dict[str, Any]:
        from .rules import registry
        lint_mod.ensure_rules()
        rows = registry.list_rules(**{k: v for k, v in filters.items() if v not in (None, "")})
        return {"count": len(rows), "summary": registry.summary(), "rules": rows}

    def rule_get(self, rule_id: str) -> dict[str, Any]:
        from .rules import registry
        lint_mod.ensure_rules()
        rule = registry.get_rule(rule_id)
        if rule is None:
            raise LookupError(f"Unknown rule '{rule_id}'.")
        return rule.row()

    # ---------------- functional check (assay) ----------------
    def assay_page(self, *, html: Optional[str] = None, url: Optional[str] = None, render_id: Optional[str] = None,
                   path: Optional[str] = None, timeout_s: int = 300, criteria: Optional[list[dict[str, Any]]] = None,
                   before: bool = False, kept: Optional[str] = None, snapshot_only: bool = False, label: str = "") -> dict[str, Any]:
        """Drive the page's controls in a real browser. ``before`` also saves what a redesign must keep (links, fields, handlers, titles);
        ``kept`` (an id from an earlier ``before``) fails the check when any of it is missing from this page."""
        snapshot_before = None
        if kept:
            snapshot_before = self.kept_get(kept)
        if render_id:
            source = self.config.renders_dir / render_id / "source.html"
            if not source.is_file():
                raise LookupError(f"Render '{render_id}' has no saved source (URL renders keep none).")
            path, html = str(source), None
        elif url:
            self.check_url(url)
            html = self._fetch_page(url)
        if html is None and not path:
            raise ValueError("page_assay needs html, url, render_id or a local path")
        page_source = html if html is not None else self._read_page_file(path)
        saved = self.kept_save(page_source, label=label or (url or path or "page"), source=url or path or "html") if before else None
        if snapshot_only:
            return {"works": True, "failed": 0, "kept": saved, "note": "Snapshot saved; run page_check with kept=<id> after the redesign."}
        result = assay_mod.run(self.config.data_dir, html=html, path=path, timeout_s=timeout_s, runner=self.assay_runner, criteria=criteria)
        if saved:
            result["kept_saved"] = saved
        if snapshot_before is not None:
            check = kept_mod.compare(snapshot_before["data"], page_source)
            result["kept"] = {"id": kept, **check}
            if not check["ok"]:
                result["works"] = False
                result["failed"] = int(result.get("failed") or 0) + check["total_missing"]
                result.setdefault("failing", []).append({"id": "KEPT", "what": "everything the page had before the redesign is still there",
                                                         "detail": f"{check['total_missing']} item(s) missing: " + ", ".join(f"{n} {k}" for k, n in check["missing_count"].items() if n),
                                                         "measured": check["missing_count"], "acts": [], "environment": {}})
        self._emit_event("vitruvius.assay.done", {"id": result.get("id"), "works": result.get("works"), "failed": result.get("failed")})
        return result

    @staticmethod
    def _read_page_file(path: Optional[str]) -> str:
        if not path:
            return ""
        target = Path(path).expanduser()
        if target.is_dir():
            target = target / "index.html"
        try:
            return target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    # ---------------- what a redesign must keep ----------------
    def kept_save(self, html: str, *, label: str = "", source: str = "") -> dict[str, Any]:
        data = kept_mod.snapshot(html)
        kept_id = uuid.uuid4().hex[:12]
        self.db.execute("INSERT INTO kept_snapshots(id, created_ts, label, source, data) VALUES (?,?,?,?,?)",
                        (kept_id, time.time(), label[:200], source[:500], json.dumps(data)))
        return {"id": kept_id, "label": label, "counts": data["counts"]}

    def kept_get(self, kept_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM kept_snapshots WHERE id = ?", (kept_id,))
        if row is None:
            raise LookupError(f"Unknown kept snapshot '{kept_id}'.")
        return {"id": row["id"], "created_ts": row["created_ts"], "label": row["label"], "source": row["source"], "data": json.loads(row["data"] or "{}")}

    def kept_list(self, limit: int = 30) -> list[dict[str, Any]]:
        out = []
        for r in self.db.query("SELECT * FROM kept_snapshots ORDER BY created_ts DESC LIMIT ?", (limit,)):
            data = json.loads(r["data"] or "{}")
            out.append({"id": r["id"], "created_ts": r["created_ts"], "label": r["label"], "source": r["source"], "counts": data.get("counts", {})})
        return out

    def _fetch_page(self, url: str) -> str:
        """The HTML of a page to check: through the family web service (one throttle and block memory for every app) when it is
        there, else fetched here (`hoard_link.fam_web.fetch_or_local`). Pages on the local network need
        `VITRUVIUS_ALLOW_LOCAL_URLS=1` and are then fetched here with the operator profile."""
        if self.config.allow_local_urls:
            from .hoard_link.web.fetch import Fetcher

            fetcher = Fetcher(profile=safety.OPERATOR_LOCAL, min_interval_s=0.0)
            try:
                result = fetcher.get(url, accept="html", respect_robots=False, timeout=30).to_dict(with_text=True)
            finally:
                fetcher.close()
        else:
            result = fam_web.fetch_or_local(url, accept="html", respect_robots=False, timeout=30)
        if not result.get("ok"):
            raise ValueError(f"Could not fetch {url}: {result.get('error') or result.get('error_kind') or 'no answer'}")
        return str(result.get("text") or "")

    def critique_render(self, render_id: str, *, focus: Optional[str] = None, use_vision: bool = True, tokens_id: Optional[str] = None,
                        waivers: Any = None, clean_review: bool = False) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM renders WHERE id = ?", (render_id,))
        if row is None:
            raise LookupError(f"Unknown render '{render_id}'.")
        tokens = self._system_tokens(tokens_id)
        render = self._render_dict(row)
        probe, html = self._render_lint_inputs(render)
        images: list[bytes] = []
        if use_vision or clean_review:
            for f in render["files"]:
                try:
                    images.append(Path(f["path"]).read_bytes())
                except OSError:
                    continue
        result = critique_mod.critique(probe=probe, html=html, focus=focus, images=images or None,
                                       link=self.link_sync if (use_vision or clean_review) else None, use_vision=use_vision,
                                       tokens=tokens, waivers=waivers, prior_waivers=waivers_mod.stored(self.db, render_id),
                                       clean_review=clean_review)
        waivers_mod.store(self.db, render_id, result["waivers"]["accepted"])
        if result.get("review") and result["review"].get("verdict"):
            rv = result["review"]
            self.db.execute("INSERT INTO reviews(render_id, created_ts, verdict, model, findings, ms) VALUES (?,?,?,?,?,?)",
                            (render_id, time.time(), rv["verdict"], rv.get("model") or "", json.dumps(rv.get("findings") or []), rv.get("ms") or 0))
        self.db.execute(
            "INSERT INTO critiques(render_id, created_ts, focus, score, heuristic_score, vision_model, findings, summary, ms) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (render_id, time.time(), focus or "", result["score"], result["heuristic_score"], result["vision_model"],
             json.dumps(result["findings"]), result["summary"], result["ms"]),
        )
        self._emit_event("vitruvius.critique.done", {"render_id": render_id, "score": result["score"], "gate": result["gate"]["state"]})
        return result

    # ---------------- tokens ----------------
    # ---------------- theme dealing with memory ----------------
    def theme_memory(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM theme_log ORDER BY id DESC LIMIT ?", (limit,))
        return [{"id": r["id"], "ts": r["ts"], "slug": r["slug"], "name": r["name"], "axes": r["axes"], "tokens_id": r["tokens_id"],
                 "prompt": r["prompt"], "seed": r["seed"]} for r in rows]

    def _theme_salt(self) -> str:
        row = self.db.one("SELECT value FROM settings WHERE key = 'theme_salt'")
        if row:
            return row["value"]
        salt = uuid.uuid4().hex[:8]
        self.db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('theme_salt', ?)", (salt,))
        return salt

    def theme_deal(self, *, prompt: str = "", genre: Optional[str] = None, n: int = 3, reroll: int = 0, seed: Optional[str] = None) -> dict[str, Any]:
        """A hand of themes clear of the last three builds (see ``themes.deal``). The same seed gives the same hand."""
        return themes_mod.deal(prompt=prompt, genre=genre, n=n, reroll=reroll, seed=seed, salt=self._theme_salt(), memory=self.theme_memory(themes_mod.MEMORY_DEPTH))

    def theme_check(self, *, axes: Optional[str] = None, face: Optional[str] = None, hue: Optional[float] = None) -> dict[str, Any]:
        return themes_mod.check(axes=axes, face=face, hue=hue, memory=self.theme_memory(themes_mod.MEMORY_DEPTH))

    def theme_record(self, theme: dict[str, Any], *, tokens_id: Optional[str], prompt: str = "", seed: str = "") -> None:
        self.db.execute("INSERT INTO theme_log(ts, slug, name, axes, tokens_id, prompt, seed) VALUES (?,?,?,?,?,?,?)",
                        (time.time(), theme["slug"], theme["name"], themes_mod.triple(theme), tokens_id, prompt[:300], seed))

    def _deal_into_brief(self, brief: dict[str, Any]) -> Optional[dict[str, Any]]:
        """With ``theme`` (a slug), ``deal`` (true) or ``genre`` in the brief, take a theme the memory allows and fold its hue, fonts, style and
        density into the brief for whatever the caller left unsaid. Returns {theme, seed, deal} or None when the brief asks for no theme."""
        wants = brief.get("theme") or brief.get("deal") or brief.get("genre")
        if not wants:
            return None
        memory = self.theme_memory(themes_mod.MEMORY_DEPTH)
        prompt = " ".join(str(x) for x in (brief.get("vibe"), brief.get("name")) if x)
        if brief.get("theme"):
            theme = themes_mod.get(str(brief["theme"]))
            if theme is None:
                raise LookupError(f"Unknown theme '{brief['theme']}'; list them with theme_list.")
            blocked = themes_mod.blocked_by(memory)
            if theme["slug"] in blocked and not brief.get("force_theme"):
                raise ValueError(f"Theme '{theme['slug']}' is blocked: {blocked[theme['slug']]}. Deal another one with theme_deal, or pass force_theme.")
            hand = {"seed": brief.get("seed") or "", "deal": [themes_mod.public(theme)], "forced": theme["slug"] in blocked}
        else:
            hand = self.theme_deal(prompt=prompt, genre=brief.get("genre"), n=3, reroll=int(brief.get("reroll") or 0), seed=brief.get("seed"))
            theme = themes_mod.get(hand["deal"][0]["slug"])
        contribution = themes_mod.as_brief(theme)
        for key in ("hue", "style", "density"):
            if brief.get(key) is None and not (key == "hue" and brief.get("base_color")):
                brief[key] = contribution[key]
        brief["fonts"] = {**contribution["fonts"], **{k: v for k, v in (brief.get("fonts") or {}).items() if v}}
        brief["theme"] = theme["slug"]
        return {"theme": theme, "seed": hand.get("seed", ""), "hand": hand}

    def tokens_generate(self, brief: dict[str, Any]) -> dict[str, Any]:
        tokens_id = uuid.uuid4().hex[:12]
        brief = dict(brief)
        dealt = self._deal_into_brief(brief)
        tokens = tokens_mod.generate(brief)
        if dealt:
            t = dealt["theme"]
            tokens["theme"] = {"slug": t["slug"], "name": t["name"], "genre": t["genre"], "posture": t["posture"], "axes": themes_mod.triple(t),
                               "seed": dealt["seed"], "material": t["material"]}
            brief["seed"] = dealt["seed"]
        css = tokens_mod.to_css(tokens)
        tailwind = tokens_mod.to_tailwind(tokens)
        self.db.execute(
            "INSERT INTO design_systems(id, name, created_ts, brief, tokens, css, tailwind) VALUES (?,?,?,?,?,?,?)",
            (tokens_id, brief.get("name") or tokens_id, time.time(), json.dumps(brief), json.dumps(tokens), css, tailwind),
        )
        if dealt:
            self.theme_record(dealt["theme"], tokens_id=tokens_id, prompt=" ".join(str(x) for x in (brief.get("vibe"), brief.get("name")) if x), seed=dealt["seed"])
        self._emit_event("vitruvius.tokens.created", {"id": tokens_id})
        row = self.tokens_get(tokens_id)
        if dealt:
            row["theme_deal"] = dealt["hand"]
        else:
            # a plan made by hand still gets told when it lands on a catalogue theme or a recent build
            fonts = brief.get("fonts") or {}
            try:
                heading = str(fonts.get("heading") or "").split(",")[0].strip().strip("'\"")
                check = self.theme_check(face=heading or None, hue=brief.get("hue") if brief.get("hue") is not None else None) if (heading or brief.get("hue") is not None) else None
            except ValueError:
                check = None
            if check and not check["clear"]:
                row["theme_check"] = check
        return row

    @staticmethod
    def _tokens_dict(r) -> dict[str, Any]:
        tokens = json.loads(r["tokens"] or "{}")
        return {"id": r["id"], "name": r["name"], "created_ts": r["created_ts"], "brief": json.loads(r["brief"] or "{}"),
               "tokens": tokens, "roles": tokens_mod.roles_of(tokens), "css": r["css"], "tailwind": r["tailwind"],
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

    # ---------------- application projects ----------------
    def app_project_render(self, id, revision=None, widths=None):
        preview = self.app_projects.preview(id, revision)
        project = self.app_projects.get(id, preview["revision"])
        context = {"id": id, "revision": preview["revision"], "source_sha256": project["source_sha256"]}
        result = self.render(url=preview["url"], widths=widths or [390, 1440], title=project["name"], _browser=self.app_browser, _app_project=context)
        result["app_project"] = context
        return result

    def app_project_call(self, id, operation, data=None, record_id=None, query=""):
        import urllib.request
        import urllib.error
        from urllib.parse import quote, urlencode
        preview = self.app_projects.preview(id)
        if operation == "list":
            path, method, body = "/api/records?" + urlencode({"q": query}), "GET", None
        elif operation == "get":
            if not record_id:
                raise ValueError("record_id is required")
            path, method, body = "/api/records/" + quote(record_id, safe=""), "GET", None
        elif operation in ("create", "update", "delete"):
            if operation != "create" and not record_id:
                raise ValueError("record_id is required")
            path, method = "/actions/" + operation, "POST"
            body = dict(data or {})
            if record_id:
                body["id"] = record_id
        else:
            raise ValueError("Unknown application operation")
        request = urllib.request.Request(preview["url"] + path, method=method, data=json.dumps(body).encode("utf-8") if body is not None else None, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.config.render_timeout_s) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            payload = json.loads(error.read())
            raise ValueError(payload.get("error", str(error))) from error

    # ---------------- references ----------------
    def reference_add(self, **kwargs) -> dict[str, Any]:
        link = kwargs.pop("link", None)
        analyze = kwargs.get("analyze", True)
        self.check_url(kwargs.get("url"))
        return references_mod.add(self.db, self.browser, self.config, link=self.link_sync if analyze else None, **kwargs)

    def reference_search(self, **kwargs) -> list[dict[str, Any]]:
        return references_mod.search(self.db, **kwargs)

    def reference_page(self, **kwargs):
        return references_mod.page(self.db, **kwargs)

    def reference_collections(self):
        return reference_collections.collections(self.db)

    def reference_import_collection(self, path):
        return reference_collections.import_collection(self.db, self.config, path)

    def design_patterns(self):
        return design_patterns.catalogue()

    def design_pattern(self, **kwargs):
        return design_patterns.generate(**kwargs)

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
            "backend": backend, "vision_enabled": bool(self.db.get_setting("vision_enabled", True)),
            "widths": list(self.db.get_setting("widths", [390, 1024, 1440])),
            "video_enabled": bool(self.db.get_setting("video_enabled", True)),
            "language": self.db.get_setting("language", "en"),
            **self._figma_token_state(),
        }

    def _figma_token_state(self) -> dict[str, Any]:
        from . import figma as figma_mod
        token = figma_mod.read_token(self.config.data_dir)
        return {"figma_token_set": bool(token), "figma_token_hint": ("…" + token[-4:]) if len(token) >= 8 else ""}

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        if "backend" in patch and patch["backend"] is not None:
            write_json_atomic(self.config.backend_json_path, patch["backend"], indent=2)
        if "vision_enabled" in patch:
            self.db.set_setting("vision_enabled", bool(patch["vision_enabled"]))
        if "widths" in patch and patch["widths"]:
            self.db.set_setting("widths", list(patch["widths"]))
        if "video_enabled" in patch:
            self.db.set_setting("video_enabled", bool(patch["video_enabled"]))
        if "language" in patch and patch["language"] in ("en", "es"):
            self.db.set_setting("language", patch["language"])
        if "figma_token" in patch and patch["figma_token"] is not None:
            from . import figma as figma_mod
            figma_mod.write_token(self.config.data_dir, str(patch["figma_token"]))
        return self.get_settings()

    # ---------------- status ----------------
    def counts(self) -> dict[str, int]:
        return {
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
            "vectors": self.db.one("SELECT COUNT(*) AS n FROM vectors")["n"],
        }

    def browser_status(self) -> dict[str, Any]:
        return self.browser.status() if hasattr(self.browser, "status") else {"ok": True}

    def status(self) -> dict[str, Any]:
        """The full picture, including the (network-probing, ~seconds) model resolution."""
        counts = self.counts()
        browser_status = self.browser_status()
        try:
            link_status = self.link_sync.status()
        except Exception as error:  # noqa: BLE001
            link_status = {"error": str(error)}
        return {
            "service": SERVICE, "version": __version__, "data_dir": str(self.config.data_dir),
            "started_at": self.started_at, "now": self.clock(), "browser": browser_status,
            "ffmpeg": ffmpeg_available(), "git": git_available(), "assay": assay_mod.available(),
            "embeddings": self.dense.status(),
            "counts": counts, "models": link_status,
        }
