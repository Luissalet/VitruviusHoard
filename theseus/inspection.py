"""Mechanical observations of local artifacts; no code from an artifact runs."""
import ast
import base64
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import struct
import zipfile

PREVIEW_BYTES = 16 * 1024 * 1024


def digest(path):
    if Path(path).is_dir():
        from .directory import inventory
        return inventory(path)["sha256"]
    result = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def asar_members(data):
    if len(data) < 16:
        raise ValueError("Incomplete ASAR header")
    header_size = struct.unpack_from("<I", data, 4)[0]
    json_size = struct.unpack_from("<I", data, 12)[0]
    header = json.loads(data[16:16 + json_size].decode("utf-8"))
    members = []

    def visit(files, prefix=""):
        for name, entry in files.items():
            path = prefix + name
            if "files" in entry:
                visit(entry["files"], path + "/")
            else:
                members.append({"name": path, "size": entry.get("size", 0),
                                "offset": 8 + header_size + int(entry.get("offset", 0)),
                                "unpacked": bool(entry.get("unpacked")),
                                "link": entry.get("link", "")})
    visit(header.get("files", {}))
    return members


def inspect_file(path):
    path = Path(path)
    if path.is_dir():
        from .directory import inventory
        result = inventory(path)
        return {"name": path.name, **result, "format": "directory", "bytes_inspected": result["size"],
                "preview_truncated": False, "observations": [],
                "warnings": ["Linked entries retain their target path; their target contents are not inventoried."]
                if any(row["kind"] == "link" for row in result["members"]) else []}
    if not path.is_file():
        raise ValueError("Choose a file to inspect")
    size = path.stat().st_size
    with path.open("rb") as handle:
        data = handle.read(PREVIEW_BYTES)
    result = {"name": path.name, "size": size, "sha256": digest(path),
              "format": "binary", "bytes_inspected": len(data),
              "preview_truncated": size > len(data), "observations": [], "warnings": []}
    observations = result["observations"]
    suffix = path.suffix.lower()
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        result['format']='png'
    elif data.startswith(b"SQLite format 3\x00"):
        result["format"] = "sqlite"
        uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
        if Path(str(path) + "-wal").exists():
            result["warnings"].append("SQLite has a WAL sidecar. This preview reads the main file; use SQLite database analysis for the captured database family.")
        with sqlite3.connect(uri, uri=True) as db:
            for name, kind, sql in db.execute("SELECT name,type,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name"):
                observations.append({"kind": kind, "name": name, "location": "sqlite_master:" + name, "text": sql})
    elif zipfile.is_zipfile(path):
        result["format"] = "zip"
        with zipfile.ZipFile(path) as archive:
            result["members"] = [{"name": row.filename, "size": row.file_size,
                                  "compressed": row.compress_size, "crc": row.CRC}
                                 for row in archive.infolist() if not row.is_dir()]
    elif suffix == ".asar":
        result["format"] = "asar"
        try:
            result["members"] = asar_members(data)
        except (ValueError, struct.error, UnicodeError) as exc:
            result["warnings"].append("ASAR header could not be decoded: " + str(exc))
    elif data[:2] == b"MZ":
        result["format"] = "pe"
        import pefile
        try:
            image = pefile.PE(str(path), fast_load=True)
            image.parse_data_directories(directories=[
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXPORT"],
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_COM_DESCRIPTOR"]])
            result["headers"] = {"machine": hex(image.FILE_HEADER.Machine),
                                 "image_base": image.OPTIONAL_HEADER.ImageBase,
                                 "entry_rva": image.OPTIONAL_HEADER.AddressOfEntryPoint,
                                 "managed": bool(image.OPTIONAL_HEADER.DATA_DIRECTORY[14].VirtualAddress)}
            result["sections"] = [{"name": s.Name.rstrip(b"\x00").decode("ascii", "replace"),
                                   "offset": s.PointerToRawData, "size": s.SizeOfRawData,
                                   "rva": s.VirtualAddress, "entropy": s.get_entropy()}
                                  for s in image.sections]
            result["imports"] = [{"library": module.dll.decode("utf-8", "replace"),
                                  "functions": [item.name.decode("utf-8", "replace") if item.name else "ordinal:" + str(item.ordinal)
                                                for item in module.imports]}
                                 for module in getattr(image, "DIRECTORY_ENTRY_IMPORT", [])]
            result["exports"] = [{"name": s.name.decode("utf-8", "replace") if s.name else "ordinal:" + str(s.ordinal),
                                  "rva": s.address} for s in getattr(getattr(image, "DIRECTORY_ENTRY_EXPORT", None), "symbols", [])]
            image.close()
        except pefile.PEFormatError as exc:
            result["warnings"].append(str(exc))
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeError:
            text = ""
        if text:
            result["format"] = "text"
            result["preview"] = text[:24000]
            if suffix == ".py":
                result["format"] = "python"
                try:
                    tree = ast.parse(text)
                    result["symbols"] = []
                    result["calls"] = []
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            result["symbols"].append({"name": node.name, "kind": type(node).__name__,
                                                      "line": node.lineno, "end_line": node.end_lineno})
                        if isinstance(node, ast.Call):
                            result["calls"].append({"target": ast.unparse(node.func), "line": node.lineno,
                                                    "certainty": "static syntax"})
                    result["imports"] = [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
                except (SyntaxError, ValueError) as exc:
                    result["warnings"].append(str(exc))
            elif suffix in {".json", ".har", ".map"}:
                try:
                    value = json.loads(text)
                    result["format"] = "json"
                    if isinstance(value, dict) and isinstance(value.get("log"), dict):
                        result["format"] = "har"
                        result["requests"] = []
                        for index, row in enumerate(value["log"].get("entries", [])):
                            request, response = row.get("request", {}), row.get("response", {})
                            result["requests"].append({"method": request.get("method"), "url": request.get("url"),
                                                       "status": response.get("status"),
                                                       "location": f"log.entries[{index}]",
                                                       "request_body": request.get("postData", {}),
                                                       "response_body": response.get("content", {})})
                    elif isinstance(value, dict) and "sources" in value and "mappings" in value:
                        result["format"] = "source-map"
                        result["sources"] = value["sources"]
                        result["names"] = value.get("names", [])
                        result["sources_content"] = value.get("sourcesContent", [])
                    else:
                        result["structure"] = list(value) if isinstance(value, dict) else {"type": type(value).__name__, "items": len(value) if isinstance(value, list) else None}
                except ValueError as exc:
                    result["warnings"].append("JSON could not be decoded: " + str(exc))
            elif suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
                result["format"] = "javascript"
                result["symbols"] = [{"name": match.group(1), "line": text.count("\n", 0, match.start()) + 1,
                                      "certainty": "lexical"}
                                     for match in re.finditer(r"(?:function\s+|(?:const|let|var)\s+)([A-Za-z_$][\w$]*)", text)]
    # Strings have true byte offsets, rather than invented source lines.
    if result["format"] in {"pe", "binary"}:
        result["strings"] = []
        for encoding, pattern in (("ascii", rb"[\x20-\x7e]{4,}"), ("utf-16le", rb"(?:[\x20-\x7e]\x00){4,}")):
            for match in re.finditer(pattern, data):
                result["strings"].append({"offset": match.start(), "encoding": encoding,
                                          "text": match.group().decode(encoding)})
        result["strings"].sort(key=lambda row: row["offset"])
    return result


def png_payload(artifact,raw,**provenance):
    actual=hashlib.sha256(raw).hexdigest()
    if actual!=artifact['sha256']:raise ValueError('The image changed since inspection; inspect its current file before reading it as an image')
    if not raw.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('Select a registered PNG image')
    return {'artifact_id':artifact['id'],'sha256':actual,'bytes':len(raw),'media_type':'image/png','base64':base64.b64encode(raw).decode('ascii'),**provenance}


def image_png(store,project_id,artifact_id):
    artifact=store.artifact(project_id,artifact_id)
    # A portable runtime document already contains its exact screenshot reply.
    # Read it in memory without a browser connection or recreating target files.
    from .native_analysis import analysis_file
    for link in store.artifact_links(project_id):
        if link['child_id']!=artifact_id:continue
        job=store.job(link['job_id'])
        if job['result'].get('operation') not in {'browser.observe','browser.scenario'}:continue
        try:
            recorded=analysis_file(store,job['id']).read_bytes()
            digest=hashlib.sha256(recorded).hexdigest()
            if digest!=job['result']['analysis_sha256']:continue
            observations=json.loads(recorded)['result']['observations']
            commands={row['message']['id'] for row in observations if row.get('direction')=='sent' and row['message'].get('method')=='Page.captureScreenshot'}
            for row in observations:
                reply=row.get('message',{})
                if row.get('direction')=='received' and reply.get('id') in commands and 'data' in reply.get('result',{}):
                    raw=base64.b64decode(reply['result']['data'],validate=True)
                    if hashlib.sha256(raw).hexdigest()==artifact['sha256']:
                        return png_payload(artifact,raw,source='retained-runtime-png',job_id=job['id'],analysis_sha256=digest)
        except (OSError,ValueError,KeyError):continue
    path=Path(artifact['path'])
    if not path.is_file():raise ValueError('The recorded PNG file is unavailable')
    return png_payload(artifact,path.read_bytes(),source='registered-file')


def excerpt(artifact, offset=0, length=4096, member=""):
    path = Path(artifact["path"])
    current_sha256 = digest(path)
    changed = current_sha256 != artifact["sha256"]
    if path.is_dir():
        if not member:
            raise ValueError("Choose a directory member to read")
        selected = next((row for row in artifact["inspection"].get("members", [])
                         if row["name"] == member and row.get("kind") == "file"), None)
        target = (path / member).resolve()
        if selected is None or not target.is_relative_to(path.resolve()) or not target.is_file():
            raise ValueError("Choose an inventoried regular member inside this directory")
        with target.open("rb") as handle:
            handle.seek(max(0, offset))
            data = handle.read(length)
        return {"artifact_id": artifact["id"], "recorded_sha256": artifact["sha256"],
                "source_changed": changed, "current_sha256": current_sha256, "member": member,
                "member_sha256": digest(target), "offset": max(0, offset), "bytes": len(data),
                "text": data.decode("utf-8", "replace"), "hex": data.hex()}
    if member:
        kind = artifact["inspection"]["format"]
        if kind == "zip":
            with zipfile.ZipFile(path) as archive:
                with archive.open(member) as handle:
                    handle.seek(max(0, offset))
                    data = handle.read(length)
        elif kind == "asar":
            row = next((r for r in artifact["inspection"].get("members", []) if r["name"] == member), None)
            if row is None or row.get("unpacked") or row.get("link"):
                raise ValueError("Choose a packed regular ASAR member")
            with path.open("rb") as handle:
                handle.seek(row["offset"] + max(0, offset))
                data = handle.read(min(length, max(0, row["size"] - max(0, offset))))
        else:
            raise ValueError("This artifact is not a supported archive")
    else:
        with path.open("rb") as handle:
            handle.seek(max(0, offset))
            data = handle.read(length)
    return {"artifact_id": artifact["id"], "recorded_sha256": artifact["sha256"],
            "source_changed": changed, "current_sha256": current_sha256, "member": member, "offset": max(0, offset),
            "bytes": len(data), "text": data.decode("utf-8", "replace"), "hex": data.hex()}
