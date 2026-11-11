"""Read-only recipe library. Discovery needs neither an engine nor a data store."""
from __future__ import annotations

import hashlib
import html
import io
import json
import mimetypes
import re
import unicodedata
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).parent
ORIGIN = "https://showcase.vitruvius.invalid"


def _words(text: str) -> set[str]:
    folded = unicodedata.normalize("NFKD", text.casefold())
    return set(re.findall(r"[a-z0-9]+", "".join(c for c in folded if not unicodedata.combining(c))))


def _rows() -> list[dict]:
    return json.loads((ROOT / "recipes.json").read_text(encoding="utf-8"))


def search(query: str = "") -> dict:
    terms = _words(query)
    rows = []
    for row in _rows():
        score = len(terms & _words(json.dumps(row, ensure_ascii=False)))
        if terms and not score:
            continue
        rows.append({"id": row["id"], "title": row["title"], "summary": row["summary"],
                     "tags": row["tags"], "sources": row["sources"], "score": score,
                     "reference_url": f"/showcase/{row['id']}/index.html",
                     "recipe_url": f"/api/showcase/{row['id']}",
                     "download_url": f"/api/showcase/{row['id']}/download"})
    return {"recipes": sorted(rows, key=lambda row: -row["score"]), "version": 1}


def read(recipe_id: str) -> dict:
    row = next((row for row in _rows() if row["id"] == recipe_id), None)
    if row is None:
        raise LookupError("Unknown showcase recipe: " + recipe_id)
    return {**row, "reference_url": f"/showcase/{recipe_id}/index.html",
            "download_url": f"/api/showcase/{recipe_id}/download",
            "remake_arguments": {"url": f"{ORIGIN}/{recipe_id}/index.html?still=1", "mode": "copy",
                                 "widths": [1440, 390], "max_rounds": 1,
                                 "label": row["title"], "note": row["prompt"][:2000]},
            "skill": (ROOT / "skills" / recipe_id / "SKILL.md").read_text(encoding="utf-8"),
            "workflow_skill": (ROOT / "SKILL.md").read_text(encoding="utf-8")}


def page(recipe_id: str) -> str:
    row = read(recipe_id)
    return (ROOT / "page.html").read_text(encoding="utf-8").replace("__TITLE__", row["title"]).replace("__ID__", recipe_id)


def resource(path: str) -> tuple[bytes, str]:
    """Resolve only shipped resources, including dynamically composed entry documents."""
    if path.startswith("/"):
        path = path[1:]
    parts = path.split("/")
    if any(part in ("", ".", "..") or "\\" in part for part in parts):
        raise LookupError("Unknown showcase resource")
    if len(parts) == 2 and parts[1] == "index.html" and parts[0] in {row["id"] for row in _rows()}:
        return page(parts[0]).encode(), "text/html; charset=utf-8"
    allowed = {"scene.js", "book.js", "reference.css", "library.js", "library.css"}
    target = (ROOT / path).resolve()
    if (path not in allowed and not path.startswith("assets/")) or ROOT.resolve() not in target.parents or not target.is_file():
        raise LookupError("Unknown showcase resource")
    return target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream"


def source(recipe_id: str, path: str = "index.html") -> dict:
    read(recipe_id)
    data, kind = resource(f"{recipe_id}/index.html" if path == "index.html" else path)
    if not (kind.startswith("text/") or path.endswith((".js", ".json"))):
        raise ValueError("Read source text or use the complete download for binary resources")
    return {"id": recipe_id, "path": path, "text": data.decode("utf-8"),
            "sha256": hashlib.sha256(data).hexdigest()}


def archive(recipe_id: str) -> bytes:
    row = read(recipe_id)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as out:
        for reference in _rows():
            document = page(reference["id"]).replace('href="/showcase/"', 'href="../index.html"')
            document = document.replace(f'href="/showcase/?recipe={reference["id"]}"', 'href="../index.html#recipe"')
            out.writestr(f"{reference['id']}/index.html", document)
        for name in ("scene.js", "book.js", "reference.css"):
            out.write(ROOT / name, name)
        for path in sorted((ROOT / "assets").iterdir()):
            if path.is_file():
                out.write(path, "assets/" + path.name)
        out.writestr("recipe.json", json.dumps(row, ensure_ascii=False, indent=2))
        out.writestr("SKILL.md", row["skill"])
        out.write(ROOT.parent / "LICENSE", "LICENSE")
        decisions = "".join(f"<h2>{html.escape(key)}</h2><p>{html.escape(value)}</p>" for key, value in row["decisions"].items())
        navigation = " ".join(f'<a href="{reference["id"]}/index.html">{html.escape(reference["title"])}</a>' for reference in _rows())
        out.writestr("index.html", '<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                     '<link rel="stylesheet" href="reference.css"><title>' + html.escape(row["title"]) + '</title>'
                     '<main style="max-width:75ch;margin:60px auto;padding:24px"><h1>' + html.escape(row["title"]) + '</h1><nav style="display:flex;gap:20px;flex-wrap:wrap;margin:32px 0">'
                     + navigation + '</nav><article id="recipe">' + decisions + '<h2>Construcción</h2><p>' + html.escape(row["prompt"]) + '</p></article></main></html>')
        out.writestr("START.txt", f"Run python -m http.server 8080 in this folder, then open http://127.0.0.1:8080/{recipe_id}/index.html\n")
    return buffer.getvalue()


def mount(context, url: str | None) -> None:
    """Serve the exact bundled origin inside the existing browser, without a local server."""
    if not url or urlsplit(url).netloc != urlsplit(ORIGIN).netloc:
        return

    def serve(route):
        try:
            data, kind = resource(urlsplit(route.request.url).path)
            route.fulfill(body=data, content_type=kind)
        except LookupError:
            route.fulfill(status=404, body="Unknown showcase resource")

    context.route(ORIGIN + "/**", serve)
