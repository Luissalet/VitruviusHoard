"""Native SQLite and structured-artifact observations with exact scalar values."""
import base64
import hashlib
import json
import math
import datetime
from pathlib import Path
import plistlib
import shutil
import sqlite3
import subprocess

OPERATIONS = [{"name": "sqlite.database", "title": "SQLite · Esquema, registros y consultas",
    "description": "Inspecciona una captura privada del archivo y su WAL: esquema, tablas, índices, relaciones y consultas de lectura. Conserva BLOB e enteros de 64 bits sin pérdida.",
    "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
        "query": {"type": "string"}, "bindings": {"type": "array"},
        "table": {"type": "string"}, "offset": {"type": "integer", "minimum": 0},
        "limit": {"type": ["integer", "null"], "minimum": 0}}}, "worker": "python"}]
OPERATIONS += [{"name": "apple.plist", "title": "Apple · Property list XML/binaria", "worker": "python",
    "description": "Lee valores plist XML o binarios sin instanciar objetos. Conserva UID, datos, fechas, enteros grandes y valores reales especiales con tipos explícitos.",
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "apple.signature", "title": "Apple · Firma y entitlements", "worker": "python", "platforms": ["darwin"],
     "description": "Inspecciona firma y entitlements y ejecuta la verificación estática con codesign de macOS. Conserva diagnósticos y fallos; no inicia la aplicación.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}}]


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


class InvalidText(bytes):
    pass


def decode_text(raw):
    try:
        return raw.decode("utf-8")
    except UnicodeError:
        return InvalidText(raw)


def value(raw):
    if isinstance(raw, InvalidText):
        return {"type": "text", "invalid_utf8": True, "base64": base64.b64encode(raw).decode("ascii")}
    if isinstance(raw, bytes):
        return {"type": "blob", "bytes": len(raw), "base64": base64.b64encode(raw).decode("ascii")}
    if isinstance(raw, int) and abs(raw) > 2**53-1:
        return {"type": "integer", "decimal": str(raw)}
    if isinstance(raw, float) and not math.isfinite(raw):
        return {"type": "real", "representation": repr(raw)}
    if isinstance(raw, float) and raw == 0 and math.copysign(1, raw) < 0:
        return {"type": "real", "representation": "-0.0"}
    return raw


def plist_value(raw):
    if isinstance(raw, plistlib.UID):
        return {"type": "uid", "decimal": str(raw.data)}
    if isinstance(raw, datetime.datetime):
        return {"type": "date", "iso8601": raw.isoformat(), "timezone": "UTC"}
    if isinstance(raw, dict):
        return {key: plist_value(item) for key, item in raw.items()}
    if isinstance(raw, list):
        return [plist_value(item) for item in raw]
    return value(raw)


def inspect_plist(source):
    raw = source.read_bytes()
    parsed = plistlib.loads(raw)
    kind = "dictionary" if isinstance(parsed, dict) else "array" if isinstance(parsed, list) else "scalar"
    pairs = parsed.items() if isinstance(parsed, dict) else enumerate(parsed) if isinstance(parsed, list) else [("$", parsed)]
    return {"format": "binary" if raw.startswith(b"bplist00") else "xml", "container_type": kind,
            "entries": [{"name": str(key), "value": plist_value(item)} for key, item in pairs],
            "limitations": ["Dates use the standard plist parser's datetime precision; exact original numeric bytes remain identified by the artifact hash."]}


def inspect_signature(source):
    executable = shutil.which("codesign")
    if not executable:
        raise ValueError("This operation requires the codesign utility from macOS")
    result = {}
    for name, arguments in [("display", ["-d", "--verbose=4"]), ("entitlements", ["-d", "--entitlements", ":-"]),
                            ("verification", ["--verify", "--deep", "--strict", "--verbose=2"])]:
        command = [executable, *arguments, str(source)]
        observed = subprocess.run(command, capture_output=True)
        result[name] = {"command": command, "exit_code": observed.returncode,
            "stdout": observed.stdout.decode("utf8", errors="replace"), "stderr": observed.stderr.decode("utf8", errors="replace")}
    result["verified_on_this_host"] = result["verification"]["exit_code"] == 0
    result["limitations"] = ["Verification describes this macOS codesign invocation and trust context; target code was not executed."]
    return result


def sqlite_database(source, parameters, output):
    # SQLite can create shared-memory sidecars even when its main file is opened
    # read-only. Read the selected database family only through a private capture.
    directory = output.parent / "sqlite-input"
    directory.mkdir()
    try:
        return inspect_sqlite_snapshot(source, parameters, directory)
    finally:
        for path in directory.iterdir():
            path.unlink()
        directory.rmdir()


def inspect_sqlite_snapshot(source, parameters, directory):
    target = directory / "database.sqlite"
    identities = {}
    candidates = [(source, target)] + [(Path(str(source)+suffix), Path(str(target)+suffix)) for suffix in ("-wal", "-shm")]
    for path, destination in candidates:
        if path.exists():
            recorded = sha(path)
            shutil.copyfile(path, destination)
            if sha(path) != recorded or sha(destination) != recorded:
                raise ValueError("Database changed while capturing its files; retry when the writer is idle")
            identities[path.name] = recorded
    # Recheck the complete family, including WAL creation/removal during capture.
    if identities != {path.name: sha(path) for path, _ in candidates if path.exists()}:
        raise ValueError("Database family changed while capturing it")
    uri = target.as_uri() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    db.text_factory = decode_text
    try:
        db.execute("PRAGMA query_only=ON")
        schema = [{"type": kind, "name": name, "table": table, "sql": sql}
                  for kind, name, table, sql in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name")]
        tables = []
        for entry in schema:
            if entry["type"] not in {"table", "view"} or entry["name"].startswith("sqlite_"):
                continue
            name = entry["name"]
            quoted = '"' + name.replace('"', '""') + '"'
            tables.append({"name": name, "kind": entry["type"],
                "columns": [list(row) for row in db.execute("PRAGMA table_xinfo(" + quoted + ")")],
                "foreign_keys": [list(row) for row in db.execute("PRAGMA foreign_key_list(" + quoted + ")")],
                "indexes": [list(row) for row in db.execute("PRAGMA index_list(" + quoted + ")")]})
        query = parameters.get("query")
        if query is None and parameters.get("table"):
            if parameters["table"] not in {row["name"] for row in tables}:
                raise ValueError("Select an existing table or view")
            query = 'SELECT * FROM "' + parameters["table"].replace('"', '""') + '"'
        rows, columns = [], []
        if query is not None:
            allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
            db.set_authorizer(lambda action, *_: sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY)
            cursor = db.execute(query, parameters.get("bindings", []))
            columns = [row[0] for row in cursor.description or []]
            offset, maximum = parameters.get("offset", 0), parameters.get("limit")
            for index, row in enumerate(cursor):
                if index < offset:
                    continue
                if maximum is not None and len(rows) >= maximum:
                    break
                rows.append({"ordinal": index, "values": [value(cell) for cell in row]})
        if identities != {path.name: sha(path) for path, _ in candidates if path.exists()}:
            raise ValueError("Database family changed during analysis; captured observations were not published")
        return {"schema": schema, "tables": tables, "query": query, "columns": columns, "rows": rows,
                "source_files": identities, "snapshot_sha256": hashlib.sha256(json.dumps(identities, sort_keys=True).encode()).hexdigest(),
                "coverage": {"row_offset": parameters.get("offset", 0), "requested_limit": parameters.get("limit"),
                             "rows_returned": len(rows)},
                "limitations": ["Queries describe the captured database family; no target program is executed.",
                                "Row order follows the supplied query; request ORDER BY when order matters."]}
    finally:
        db.close()


def main():
    import sys
    request_path, output_path = map(Path, sys.argv[1:3])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    source = Path(request["path"])
    if source.is_dir():
        from directory import inventory
        before = inventory(source)["sha256"]
    else:
        before = sha(source)
    if request.get('expected_input_sha256') and before != request['expected_input_sha256']:
        raise ValueError('Retained analysis document changed; its receipt hash no longer matches')
    if request['operation'] in {'javascript.reconcile_runtime','browser.reconcile_sources','browser.compare','browser.export_scripts'}:
        source_bytes = source.read_bytes()
        if hashlib.sha256(source_bytes).hexdigest() != before:
            raise ValueError('Retained analysis document changed while reading')
        if request['operation']=='browser.export_scripts':
            from web_sources import export_sources
            result=export_sources(source_bytes,request['parameters']['output_directory'])
        elif request['operation']=='browser.compare':
            from browser_compare import compare
            result=compare(request,source_bytes)
        else:
            from javascript_runtime import reconcile
            result = reconcile(request, source_bytes)
    elif request["operation"] == "sqlite.database":
        result = sqlite_database(source, request["parameters"], output_path)
    elif request["operation"] in {"capture.fields", "capture.packets"}:
        from packets import inspect_capture
        result = inspect_capture(source, request["operation"], request["parameters"], output_path, before)
    elif request["operation"] == "apple.plist":
        result = inspect_plist(source)
    elif request["operation"] == "apple.signature":
        result = inspect_signature(source)
    elif request["operation"] == "crash.recording":
        from recordings import inspect_core
        result = inspect_core(source, request["parameters"])
    elif request["operation"].startswith("signal."):
        from signals import inspect_signal
        result = inspect_signal(source, request["operation"], request["parameters"], output_path, before)
    elif request["operation"].startswith("android."):
        from android import inspect_android
        result = inspect_android(source, request["operation"], request["parameters"], output_path, before)
    elif request["operation"] == "network.qlog":
        from qlog import inspect_qlog
        result = inspect_qlog(source, request["parameters"])
    elif request["operation"].startswith("firmware."):
        from firmware import inspect_firmware
        inspect_firmware(source, request["operation"], request["parameters"], output_path, before)
        print(json.dumps({"ok": True, "operation": request["operation"]}))
        return
    else:
        raise ValueError("Unknown structured-artifact operation")
    document = {"operation": request["operation"], "artifact_sha256": request.get('source_artifact_sha256', before), "input_sha256": before,
                "engine": "Theseus native structured analysis", "runtime": sys.version.split()[0], "result": result}
    output_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "operation": request["operation"]}))


if __name__ == "__main__":
    main()
