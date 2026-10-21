"""Offline protocol observations through an installed free packet decoder."""
import datetime
from decimal import Decimal
import hashlib
import json
import re
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
            "packet_limit": {"type": "integer", "minimum": 1}, "check_checksums": {"type": "boolean"},
            "raw": {"type": "boolean"}, "offset": {"type": "integer", "minimum": 0},
            "limit": {"type": ["integer", "null"], "minimum": 0}}}},
    {"name": "capture.summary", "title": "Capturas · Resumen de tráfico",
     "description": "Resume una captura PCAP/PCAPNG grabada: tipo, encapsulación, intervalo, extremos con puertos, consultas DNS con sus respuestas, SNI de TLS, distribución de protocolos y URI HTTP con la consulta redactada. No captura tráfico.",
     "worker": "python", "inputSchema": {"type": "object", "additionalProperties": False,
        "properties": {"max_items": {"type": "integer", "minimum": 1, "maximum": 100000}}}},
]

SUMMARY_FIELDS = ["frame.time_epoch", "frame.protocols", "ip.src", "ip.dst", "ipv6.src", "ipv6.dst", "tcp.srcport", "tcp.dstport", "udp.srcport", "udp.dstport",
                  "dns.flags.response", "dns.qry.name", "dns.a", "dns.aaaa", "tls.handshake.extensions_server_name", "http.request.uri"]


def capinfos_facts(metadata):
    facts = {}
    for line in (metadata or {}).get("stdout", "").splitlines():
        name, _, value = line.partition(":")
        facts.setdefault(name.strip(), value.strip())
    def number(name, kind=int):
        found = re.search(r"\d[\d,]*(?:\.\d+)?", facts.get(name, ""))
        return kind(found.group(0).replace(",", "")) if found else None
    return facts, number


def utc(seconds):
    """An epoch instant as ISO 8601 UTC, keeping every recorded fractional digit."""
    whole = int(seconds // 1)
    fraction = format(seconds - whole, "f").partition(".")[2].rstrip("0")
    stamp = datetime.datetime.fromtimestamp(whole, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return stamp + ("." + fraction if fraction else "") + "Z"


def summarize(text, metadata, maximum):
    """Aggregate tab-separated tshark field rows into the capture summary contract."""
    endpoints, protocols, dns, sni, uris = {}, {}, {}, set(), []
    unattributed, unattributed_packets, redacted, times, count = set(), 0, 0, [], 0
    for line in text.splitlines():
        values = dict(zip(SUMMARY_FIELDS, line.split("\t")))
        count += 1
        if values.get("frame.time_epoch"):
            times.append(Decimal(values["frame.time_epoch"]))
        split = lambda name: [item for item in values.get(name, "").split(",") if item]
        for protocol in set(filter(None, values.get("frame.protocols", "").split(":"))):
            protocols[protocol] = protocols.get(protocol, 0) + 1
        source = (split("ip.src") or split("ipv6.src") or [None])[0]
        target = (split("ip.dst") or split("ipv6.dst") or [None])[0]
        transport = "tcp" if split("tcp.srcport") else "udp" if split("udp.srcport") else None
        ports = (split(transport + ".srcport")[0], split(transport + ".dstport")[0]) if transport else (None, None)
        for address, port in ((source, ports[0]), (target, ports[1])):
            if address:
                key = (address, int(port) if port else None)
                endpoints[key] = endpoints.get(key, 0) + 1
        names, answers = split("dns.qry.name"), split("dns.a") + split("dns.aaaa")
        if names:
            for name in names:
                dns.setdefault(name, [])
            if values.get("dns.flags.response") in {"1", "True", "true"}:
                for name in names[:1]:
                    dns[name].extend(answer for answer in answers if answer not in dns[name])
        elif answers:
            unattributed_packets += 1
            unattributed.update(answers)
        sni.update(split("tls.handshake.extensions_server_name"))
        for uri in [values.get("http.request.uri", "")] if values.get("http.request.uri") else []:
            if "?" in uri:
                uri, redacted = uri.split("?", 1)[0] + "?<redacted>", redacted + 1
            uris.append(uri)
    facts, number = capinfos_facts(metadata)
    rows = sorted(({"address": address, "port": port, "packet_count": count} for (address, port), count in endpoints.items()),
                  key=lambda row: (-row["packet_count"], row["address"], row["port"] if row["port"] is not None else -1))
    queries = [{"query": name, "response_addresses": addresses[:maximum], "response_address_count": len(addresses)} for name, addresses in sorted(dns.items())]
    distribution = sorted(({"protocol": name, "packet_count": count} for name, count in protocols.items()), key=lambda row: (-row["packet_count"], row["protocol"]))
    distinct_uris = sorted(set(uris))
    clipped = any(len(items) > maximum for items in (rows, queries, sni, distribution, distinct_uris, unattributed))
    return {"file_type": facts.get("File type") or None, "encapsulation": facts.get("File encapsulation") or None,
            "packet_count": count, "capture_start": utc(min(times)) if times else None, "capture_end": utc(max(times)) if times else None,
            "capture_duration_seconds": float(max(times) - min(times)) if times else None,
            "snapshot_length": number("Packet size limit"),
            "endpoints": rows[:maximum], "endpoint_count": len(rows), "dns_queries": queries[:maximum], "dns_query_count": len(queries),
            "tls_sni_values": sorted(sni)[:maximum], "tls_sni_count": len(sni),
            "protocol_distribution": distribution[:maximum], "protocol_count": len(distribution),
            "http_request_uris": distinct_uris[:maximum], "http_request_uri_count": len(distinct_uris), "http_uri_redaction_count": redacted,
            "unattributed_dns_addresses": sorted(unattributed)[:maximum], "unattributed_dns_address_count": len(unattributed),
            "unattributed_dns_packet_count": unattributed_packets, "coverage": "partial" if clipped else "complete"}


CAPTURE_MAGICS = {bytes.fromhex(value) for value in ("d4c3b2a1", "a1b2c3d4", "4d3cb2a1", "a1b23c4d", "34cdb2a1", "a1b2cd34", "0a0d0d0a")}


def packet_count(metadata):
    """Total packets in the file as capinfos reports them, or None."""
    for line in (metadata or {}).get("stdout", "").splitlines():
        name, _, value = line.partition(":")
        if name.strip() == "Number of packets" and value.strip().isdigit():
            return int(value.strip())
    return None


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
        original = source.read_bytes()
        # The operation reads PCAP and PCAPNG only; TShark's format heuristics would accept empty or unrelated bytes.
        if original[:4] not in CAPTURE_MAGICS:
            raise ValueError("Not a PCAP or PCAPNG capture: the file does not start with a capture header")
        snapshot.write_bytes(original)
        if hashlib.sha256(snapshot.read_bytes()).hexdigest() != expected_sha256:
            snapshot.unlink()
            raise ValueError("Capture changed before a stable snapshot could be read")
        if operation == "capture.summary":
            command += ["-n", "-r", str(snapshot), "-T", "fields", "-E", "separator=/t", "-E", "aggregator=,", "-E", "occurrence=a"]
            command += [option for field in SUMMARY_FIELDS for option in ("-e", field)]
        else:
            command += ["-n", "-r", str(snapshot), "-T", "json", "--no-duplicate-keys"]
        if operation == "capture.summary":
            pass
        elif parameters.get("two_pass"):
            command += ["-2"]
        if parameters.get("packet_limit"):
            command += ["-c", str(parameters["packet_limit"])]
        if parameters.get("check_checksums"):
            command += [option for protocol in ("ip", "tcp", "udp") for option in ("-o", protocol + ".check_checksum:TRUE")]
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
    if operation == "capture.summary":
        return {"engine": {"executable": executable, "sha256": hashlib.sha256(Path(executable).read_bytes()).hexdigest(),
                           "version": version.splitlines()[0]}, "command": command, "source_path": str(source),
                "capture_metadata": metadata, "snapshot_sha256": expected_sha256, "warnings": warnings,
                **summarize(text, metadata, parameters.get("max_items", 500)),
                "limitations": ["Offline recorded bytes only; no live acquisition or network requests.",
                    "Endpoints count each packet once for its source and once for its destination; ports come from TCP or UDP only.",
                    "DNS response addresses are attributed to the first question of the response; answers without a question are listed as unattributed.",
                    "HTTP request URIs keep the path; any query string is replaced by <redacted>.",
                    "Encrypted traffic remains encrypted; TLS server names come from cleartext handshakes only."]}
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
    # A packet limit stops reading the file; packets after it were neither decoded nor filtered.
    total = packet_count(metadata) if operation != "capture.fields" else None
    limited = parameters.get("packet_limit")
    unread = None if not limited else (max(0, total - limited) if total is not None else "unknown")
    return {"engine": {"executable": executable, "sha256": hashlib.sha256(Path(executable).read_bytes()).hexdigest(),
                       "version": version.splitlines()[0]}, "command": command,
            "fields" if operation == "capture.fields" else "packets": selected,
            "source_path": str(source), "capture_metadata": metadata, "snapshot_sha256": expected_sha256, "warnings": warnings, "coverage": {"decoded_matching_records": len(records), "offset": offset,
                "limit": maximum, "returned": len(selected),
                "has_more": offset+len(selected) < len(records) or (unread not in (None, 0)),
                **({"packet_limit": limited, "capture_packets": total, "unread_packets": unread} if limited else {})},
            "limitations": ["Offline recorded bytes only; no live acquisition or network requests.",
                "Encrypted traffic remains encrypted without recorded decryption material; no key recovery is inferred.",
                "HTTP/3 and QUIC fields depend on installed dissectors and recorded decryption material. qlog is a separate structured recording format."]}
