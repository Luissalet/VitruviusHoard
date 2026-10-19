"""Content identity for selected directories, without following linked entries."""
import hashlib
import json
import os
from pathlib import Path


def inventory(path):
    root = Path(path)
    rows = []
    pending = [root]
    while pending:
        directory = pending.pop()
        for item in directory.iterdir():
            relative = item.relative_to(root).as_posix()
            if item.is_symlink() or getattr(item.lstat(), "st_reparse_tag", 0) == 0xA0000003:
                rows.append([relative, "link", os.readlink(item), 0])
            elif item.is_dir():
                rows.append([relative, "directory", "", 0])
                pending.append(item)
            elif item.is_file():
                sha = hashlib.sha256()
                with item.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        sha.update(chunk)
                rows.append([relative, "file", sha.hexdigest(), item.stat().st_size])
            else:
                rows.append([relative, "special", "", 0])
    rows.sort(key=lambda row: row[0].encode("utf-8"))
    encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return {"sha256": hashlib.sha256(encoded).hexdigest(),
            "size": sum(row[3] for row in rows), "members": [
                {"name": row[0], "kind": row[1], "size": row[3],
                 **({"sha256": row[2]} if row[1] == "file" else {"target": row[2]} if row[1] == "link" else {})}
                for row in rows], "identity_schema": "theseus/directory-1"}
