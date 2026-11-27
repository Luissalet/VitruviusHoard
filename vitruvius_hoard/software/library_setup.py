"""Prepare an editable first library entirely from the installed package."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

from .. import presets, reference_collections
from ..config import Config
from ..db import Database
from ..hoard_link.atomic import read_json, write_json_atomic
from ..ingest.markdown import chunk_markdown
from ..motion import Composition, MotionStore, templates

PACKAGE = Path(__file__).resolve().parents[1]
SOURCE = "bundled-design-library"
RECEIPT = "library-preparation.json"


def receipt(profile):
    saved = read_json(profile / RECEIPT)
    return saved if isinstance(saved, dict) else {}


def _catalogue(db, generation, catalogue, recipes, patterns):
    existing = db.one("SELECT kind, docs, chunks FROM sources WHERE id = ?", (SOURCE,))
    if existing:
        if existing["kind"] != "bundled":
            raise ValueError("The bundled library source ID is already in use")
        return None

    now = time.time()
    documents = []
    for preset in catalogue:
        fonts = preset["fonts"]
        text = "\n\n".join((preset["character"], ", ".join(preset["keywords"]),
                             f"{fonts['heading']} / {fonts['body']} / {fonts['mono']}"))
        documents.append((f"presets/{preset['name']}", preset["title"], text, "catalog", ""))
    for recipe in recipes:
        text = "\n\n".join((recipe["summary"], ", ".join(recipe["tags"]), *recipe["decisions"].values()))
        documents.append((f"showcase/{recipe['id']}", recipe["title"], text, "catalog", "es"))
    for pattern in patterns:
        documents.append((f"patterns/{pattern['id']}", pattern["name"],
                          "\n\n".join((pattern["name_es"], pattern["description"], ", ".join(pattern["tags"]))),
                          "catalog", ""))
    for path in sorted((PACKAGE / "webguide" / "guides").glob("*/*.md")):
        documents.append((path.relative_to(PACKAGE).as_posix(), path.stem,
                          path.read_text(encoding="utf-8"), "guide", "en"))

    with db.transaction() as conn:
        inserted = conn.execute(
            """INSERT OR IGNORE INTO sources(id, kind, category, structured, status, commit_sha, last_ingest_ts, note)
               VALUES (?, 'bundled', 'design', 1, 'ready', ?, ?, ?)""",
            (SOURCE, generation, now, "Local presets, guides, patterns and showcase recipes from the installed package."),
        )
        if not inserted.rowcount:
            return None
        pieces = 0
        for path, title, text, kind, lang in documents:
            parsed = chunk_markdown(text, default_title=title)
            data = text.encode("utf-8")
            row = conn.execute(
                """INSERT INTO documents(source_id, path, title, kind, lang, bytes, hash, updated_ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (SOURCE, path, parsed["title"], kind, lang, len(data), hashlib.sha256(data).hexdigest(), now),
            )
            conn.executemany(
                "INSERT INTO chunks(document_id, heading, ordinal, text, tokens) VALUES (?, ?, ?, ?, ?)",
                [(row.lastrowid, chunk["heading"], chunk["ordinal"], chunk["text"], chunk["tokens"])
                 for chunk in parsed["chunks"]],
            )
            pieces += len(parsed["chunks"])

        pairings = set()
        for preset in catalogue:
            swatches = preset["swatches"]["dark" if preset["dark_first"] else "light"]
            colors = json.dumps(swatches)
            fonts = preset["fonts"]
            conn.execute(
                """INSERT INTO styles(source_id, name, slug, description, keywords, colors, typography, raw)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (SOURCE, preset["title"], preset["name"], preset["character"], json.dumps(preset["keywords"]),
                 colors, json.dumps(fonts), json.dumps(preset, ensure_ascii=False)),
            )
            conn.execute(
                "INSERT INTO palettes(source_id, name, product_type, colors, notes) VALUES (?, ?, ?, ?, ?)",
                (SOURCE, preset["title"], preset["genre"], colors, preset["character"]),
            )
            faces = (fonts["heading"], fonts["body"], fonts["mono"])
            if faces not in pairings:
                pairings.add(faces)
                conn.execute(
                    """INSERT INTO font_pairings(source_id, heading, body, mono, category, notes)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (SOURCE, *faces, preset["genre"], preset["title"]),
                )
        conn.execute("UPDATE sources SET docs = ?, chunks = ? WHERE id = ?", (len(documents), pieces, SOURCE))
    return generation


def prepare(services, profile, previous):
    """Install missing starter data and return the changes this operation can reverse."""
    state = receipt(profile)
    choices = [presets.summary(preset) for preset in presets.catalogue()]
    recipes = json.loads((PACKAGE / "showcase" / "recipes.json").read_text(encoding="utf-8"))
    patterns = services.design_patterns()
    motion_rule_count = len(services.library_rules(area="motion", limit=200))
    generation = uuid4().hex
    changes = {"token": generation, "previous": previous, "previous_report": state.get("report"),
               "source": None, "motion": {}, "references": {}}
    report = {"errors": [], "added": {}, "available": {}, "undo": None}
    errors = report["errors"]

    def save_progress():
        if any(changes[field] for field in ("previous", "source", "motion", "references")):
            state["undo"] = changes
            report["undo"] = {"tool": "design_library_undo", "arguments": {"token": generation}}
            write_json_atomic(profile / RECEIPT, state)

    save_progress()
    try:
        changes["source"] = _catalogue(services.db, generation, choices, recipes, patterns)
        save_progress()
    except (OSError, ValueError, sqlite3.Error) as error:
        errors.append({"part": "catalogue", "message": str(error)})

    motion = MotionStore(services.config.data_dir)
    motion_ids = {}
    for name, seed in templates().items():
        id = hashlib.sha256(f"vitruvius-bundled-motion:{name}".encode()).hexdigest()[:32]
        motion_ids[name] = id
        try:
            motion.get(id)
        except LookupError:
            try:
                created = motion.save(Composition.model_validate(seed), id)
            except ValueError:
                # A simultaneous save of this exact ID wins.
                motion.get(id)
            else:
                changes["motion"][id] = created["composition"]
                save_progress()

    collection = reference_collections.import_collection(
        services.db, services.config, str(PACKAGE / "showcase" / "reference-library.json"), track_created=True,
    )
    changes["references"] = collection["created"]
    save_progress()
    errors.extend({"part": "references", **error} for error in collection["errors"])

    library_counts = services.counts()
    report["available"] = {
        **{key: library_counts[key] for key in ("sources", "documents", "chunks", "styles", "palettes", "font_pairings")},
        "presets": len(choices), "recipes": len(recipes), "patterns": len(patterns),
        "motion_rules": motion_rule_count,
        "motion_examples": len(motion_ids), "references": len(collection["references"]),
    }
    report["added"] = {
        "catalogue": bool(changes["source"]), "motion_examples": len(changes["motion"]),
        "references": collection["imported"],
    }
    report.update(ok=not errors, motion=motion_ids, collection=collection["collection"])
    state["report"] = {key: value for key, value in report.items() if key != "undo"}
    write_json_atomic(profile / RECEIPT, state)
    return report


def undo_data(profile, changes):
    """Remove only the catalogue, intact examples and reference rows created by this receipt."""
    config = Config(data_dir=profile / "design")
    removed = {"catalogue": False, "motion_examples": 0, "references": 0}
    retained = []
    if config.db_path.is_file():
        db = Database(config.db_path)
        try:
            with db.transaction() as conn:
                row = conn.execute("SELECT kind, commit_sha FROM sources WHERE id = ?", (SOURCE,)).fetchone()
                if changes["source"] and row and row["kind"] == "bundled" and row["commit_sha"] == changes["source"]:
                    chunk_ids = "SELECT c.id FROM chunks c JOIN documents d ON d.id = c.document_id WHERE d.source_id = ?"
                    conn.execute(f"DELETE FROM chunk_vectors WHERE chunk_id IN ({chunk_ids})", (SOURCE,))
                    conn.execute(f"DELETE FROM chunks WHERE id IN ({chunk_ids})", (SOURCE,))
                    for table in ("documents", "styles", "palettes", "font_pairings"):
                        conn.execute(f"DELETE FROM {table} WHERE source_id = ?", (SOURCE,))
                    conn.execute("DELETE FROM sources WHERE id = ?", (SOURCE,))
                    removed["catalogue"] = True
                elif changes["source"] and row:
                    retained.append(SOURCE)
                for id, created_ts in changes["references"].items():
                    deleted = conn.execute("DELETE FROM references_t WHERE id = ? AND created_ts = ?", (id, created_ts))
                    removed["references"] += deleted.rowcount
                    if not deleted.rowcount and conn.execute("SELECT id FROM references_t WHERE id = ?", (id,)).fetchone():
                        retained.append(id)
        finally:
            db.close()

    if changes["motion"] and (config.data_dir / "motion.sqlite3").is_file():
        motion = MotionStore(config.data_dir)
        for id, composition in changes["motion"].items():
            if motion.discard_initial(id, composition):
                removed["motion_examples"] += 1
            else:
                try:
                    motion.get(id)
                except LookupError:
                    continue
                retained.append(id)
    return {"removed": removed, "retained": retained}
