"""Portable, repeatable imports of captured reference collections."""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import time
import uuid
from pathlib import Path

from PIL import Image

from .references import extract_palette


def collections(db):
    rows = db.query("SELECT analysis FROM references_t ORDER BY created_ts DESC, id DESC")
    found = {}
    for row in rows:
        collection = json.loads(row["analysis"] or "{}").get("collection")
        if collection:
            item = found.setdefault(collection["id"], {"id": collection["id"], "name": collection["name"], "count": 0})
            item["count"] += 1
    return list(found.values())


def import_collection(db, config, path: str):
    """Copy snapshots into the gallery; source material is never executed."""
    manifest_path = Path(path).expanduser().resolve()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ValueError(f"Cannot read collection manifest: {error}") from error
    if not isinstance(manifest, dict) or manifest.get("format") != "vitruvius-reference-collection/v1":
        raise ValueError("Expected vitruvius-reference-collection/v1 manifest")
    collection_id, name, entries = manifest.get("id"), manifest.get("name"), manifest.get("entries")
    if not isinstance(collection_id, str) or not collection_id.strip() or not isinstance(name, str) or not name.strip() or not isinstance(entries, list):
        raise ValueError("Collection needs id, name and entries")
    root = Path(config.references_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    result = {"collection": {"id": collection_id, "name": name}, "imported": 0, "reused": 0, "errors": [], "references": []}
    keys = set()
    for index, entry in enumerate(entries):
        stage = None
        published = None
        try:
            if not isinstance(entry, dict) or not isinstance(entry.get("key"), str) or not entry["key"]:
                raise ValueError("Entry needs a nonempty key")
            for field in ("title", "description", "url", "note", "vibe"):
                if field in entry and not isinstance(entry[field], str):
                    raise ValueError(f"{field} must be text")
            for field in ("tags", "fonts", "libs"):
                if field in entry and (not isinstance(entry[field], list) or any(not isinstance(value, str) for value in entry[field])):
                    raise ValueError(f"{field} must be a list of text values")
            if "motion" in entry and not isinstance(entry["motion"], dict):
                raise ValueError("motion must be an object")
            key = entry["key"]
            if key in keys:
                raise ValueError(f"Duplicate entry key: {key}")
            keys.add(key)
            assets, hashes = {}, {}
            files = entry.get("files", {})
            if not isinstance(files, dict):
                raise ValueError("files must be an object")
            if not files.get("desktop"):
                raise ValueError("Entry needs a desktop snapshot")
            for kind in ("desktop", "mobile"):
                if not files.get(kind):
                    continue
                source = (manifest_path.parent / files[kind]).resolve()
                data = source.read_bytes()
                with Image.open(io.BytesIO(data)) as image:
                    image.verify()
                    extension = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}.get(image.format)
                if not extension:
                    raise ValueError(f"Unsupported snapshot format: {kind}")
                assets[f"{kind}.{extension}"] = data
                hashes[kind] = hashlib.sha256(data).hexdigest()
            metadata = entry.get("metadata", {})
            if not isinstance(metadata, dict):
                raise ValueError("metadata must be an object")
            provenance = {**metadata, "id": collection_id, "name": name, "key": key, "snapshot_sha256": hashes}
            # Metadata edits are versions too: never silently reuse an old description.
            identity = json.dumps({"collection": collection_id, "entry": entry, "snapshots": hashes}, sort_keys=True, ensure_ascii=False)
            ref_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
            was_new = False
            with db.tx():
                if db.one("SELECT id FROM references_t WHERE id = ?", (ref_id,)):
                    pass
                else:
                    stage = root / (".import-" + uuid.uuid4().hex)
                    stage.mkdir()
                    stored = {}
                    for filename, data in assets.items():
                        (stage / filename).write_bytes(data)
                        stored[filename.split(".")[0]] = str(root / ref_id / filename)
                    palette = extract_palette(str(stage / next(f for f in assets if f.startswith("desktop."))), n=8)
                    destination = root / ref_id
                    if destination.exists():
                        # Reference deletion retains assets. Restore its index only
                        # when those original snapshots still match, without overwriting.
                        if not destination.is_dir() or any((destination / filename).read_bytes() != data for filename, data in assets.items()):
                            raise ValueError(f"Saved snapshot differs from the collection: {ref_id}")
                    else:
                        stage.rename(destination)
                        stage = None
                        published = destination
                    db.execute(
                        "INSERT INTO references_t(id,created_ts,url,title,description,tags,note,vibe,files,palette,fonts,libs,motion,analysis) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (ref_id, time.time(), entry.get("url", ""), entry.get("title", key), entry.get("description", ""),
                         json.dumps(entry.get("tags", [])), entry.get("note", ""), entry.get("vibe", ""), json.dumps(stored),
                         json.dumps(palette), json.dumps(entry.get("fonts", [])), json.dumps(entry.get("libs", [])),
                         json.dumps(entry.get("motion", {})), json.dumps({"collection": provenance}, ensure_ascii=False)),
                    )
                    was_new = True
            result["imported" if was_new else "reused"] += 1
            published = None
            result["references"].append({"key": key, "id": ref_id})
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as error:
            result["errors"].append({"index": index, "key": entry.get("key") if isinstance(entry, dict) else None, "error": str(error)})
        finally:
            # Only flat, newly created folders owned by this invocation are removed.
            for owned in (stage, published):
                if owned is not None and owned.resolve().parent == root:
                    for asset in owned.iterdir():
                        asset.unlink()
                    owned.rmdir()
    result["ok"] = not result["errors"]
    return result
