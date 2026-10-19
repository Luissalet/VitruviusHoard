"""Offline protocol observations through an installed free packet decoder."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

OPERATIONS = [
    {"name": "capture.fields", "title": "Capturas · Campos de protocolos",
     "description": "Enumera campos del TShark instalado, filtrados por nombre, protocolo o descripción. El catálogo no demuestra que un campo exista en la captura seleccionada.",
     "worker": "python", "inputSchema": {"type": "object", "additionalProperties": False,
        "properties": {"match": {"type": "string"}, "kind": {"enum": ["protocols", "fields"]}, "protocol": {"type": "string"}, "offset": {"type": "integer", "minimum": 0},
                       "limit": {"type": ["integer", "null"], "minimum": 0}}}},
    {"name": "capture.packets", "title": "Capturas · Paquetes y protocolos",
     "description": "Lee PCAP/PCAPNG sin capturar tráfico en vivo: árboles de campos, filtro de visualización, campos seleccionados y bytes originales opcionales. Conserva errores y avisos del decodificador.",
     "worker": "python", "inputSchema": {"type": "object", "additionalProperties": False,
        "properties": {"display_filter": {"type": "string"}, "fields": {"type": "array", "items": {"type": "string"}},
            "decode_as": {"type": "array", "items": {"type": "string"}}, "two_pass": {"type": "boolean"},
            "packet_limit": {"type": "integer", "minimum": 1},
            "raw": {"type": "boolean"}, "offset": {"type": "integer", "minimum": 0},
            "limit": {"type": ["integer", "null"], "minimum": 0}}}},
]


def engine():
    candidates = [os.environ.get("THESEUS_TSHARK"), shutil.which("tshark"),
        "D:/LocalAI/tools/wireshark779/portable/App/Wireshark/tshark.exe",
        "C:/Program Files/Wireshark/tshark.exe"]
    return next((str(Path(value).resolve()) for value in candidates if value and Path(value).is_file()), None)


def inspect_capture(source, operation, parameters, output, expected_sha256):
    executable = engine()
    if not executable:
        raise ValueError("Install free TShark or set THESEUS_TSHARK to its executable")
    config = output.parent / "packet-config"
    config.mkdir(exist_ok=True)
    environment = dict(os.environ, WIRESHARK_CONFIG_DIR=str(config))
    version = subprocess.run([executable, "--version"], env=environment, capture_output=True, check=True).stdout.decode("utf8", errors="replace")
    command = [executable]
    snapshot = output.parent / "packet-input.bin"
    if operation == "capture.fields":
        command += ["-G", parameters.get("kind", "fields")]
    else:
        snapshot.write_bytes(source.read_bytes())
        if hashlib.sha256(snapshot.read_bytes()).hexdigest() != expected_sha256:
            snapshot.unlink()
            raise ValueError("Capture changed before a stable snapshot could be read")
        command += ["-n", "-r", str(snapshot), "-T", "json", "--no-duplicate-keys"]
        if parameters.get("two_pass"):
            command += ["-2"]
        if parameters.get("packet_limit"):
            command += ["-c", str(parameters["packet_limit"])]
        for rule in parameters.get("decode_as", []):
            command += ["-d", rule]
        if parameters.get("display_filter"):
            command += ["-Y", parameters["display_filter"]]
        for field in parameters.get("fields", []):
            command += ["-e", field]
        if parameters.get("raw"):
            command += ["-x"]
    metadata = None
    capinfos = os.environ.get("THESEUS_CAPINFOS") or shutil.which("capinfos") or str(Path(executable).with_name("capinfos.exe" if os.name == "nt" else "capinfos"))
    try:
        if operation != "capture.fields" and Path(capinfos).is_file():
            info = subprocess.run([capinfos, "-M", str(snapshot)], env=environment, capture_output=True)
            metadata = {"command": [capinfos, "-M", str(snapshot)], "exit_code": info.returncode,
                "stdout": info.stdout.decode("utf8", errors="replace"), "stderr": info.stderr.decode("utf8", errors="replace"),
                "executable_sha256": hashlib.sha256(Path(capinfos).read_bytes()).hexdigest()}
        observed = subprocess.run(command, env=environment, capture_output=True)
    finally:
        snapshot.unlink(missing_ok=True)
    warnings = observed.stderr.decode("utf8", errors="replace")
    if observed.returncode:
        raise ValueError("Packet decoder failed ("+str(observed.returncode)+"): "+warnings)
    text = observed.stdout.decode("utf8")
    if operation == "capture.fields":
        records = []
        for line in text.splitlines():
            values = line.split("\t")
            if parameters.get("match", "").casefold() not in line.casefold():
                continue
            if parameters.get("kind", "fields") == "protocols":
                records.append({"name": values[0], "short_name": values[1], "protocol": values[2]})
            elif values[0] == "F" and (not parameters.get("protocol") or values[4] == parameters["protocol"]):
                records.append({"name": values[1], "field": values[2], "type": values[3],
                    "protocol": values[4], "attributes": values[5:]})
    else:
        records = json.loads(text)
    offset, maximum = parameters.get("offset", 0), parameters.get("limit")
    selected = records[offset:] if maximum is None else records[offset:offset+maximum]
    return {"engine": {"executable": executable, "sha256": hashlib.sha256(Path(executable).read_bytes()).hexdigest(),
                       "version": version.splitlines()[0]}, "command": command,
            "fields" if operation == "capture.fields" else "packets": selected,
            "source_path": str(source), "capture_metadata": metadata, "snapshot_sha256": expected_sha256, "warnings": warnings, "coverage": {"decoded_matching_records": len(records), "offset": offset,
                "limit": maximum, "returned": len(selected), "has_more": offset+len(selected) < len(records)},
            "limitations": ["Offline recorded bytes only; no live acquisition or network requests.",
                "Encrypted traffic remains encrypted without recorded decryption material; no key recovery is inferred.",
                "HTTP/3 and QUIC fields depend on installed dissectors and recorded decryption material. qlog is a separate structured recording format."]}
