"""Serve each owned preview at a stable, separate loopback origin."""
from __future__ import annotations

import re
import threading
import uuid
from contextlib import closing
from html import escape
from html.parser import HTMLParser
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import accumulate
from pathlib import Path
from urllib.parse import urlsplit

from .hoard_link.app_bridge import BRIDGE_JS
from .hoard_link.guard import DEV_ORIGINS, check_request
from .transfer_assistant.reply import NDJSON, ReplyError
from .transfer_assistant.voice import TransferVoice, VOICE_PREFIX, _json

SCRIPT_ROOT = "/__vitruvius_preview__/"
# Additional preview-only scripts live alongside the application package.
PREVIEW_SCRIPTS = ("preview-inspector.js", "preview-refresh.js")
SCRIPT_DIR = Path(__file__).with_name("preview_scripts")


class _DocumentEnds(HTMLParser):
    CDATA_CONTENT_ELEMENTS = ("script", "style", "textarea", "title")
    head_end = None
    body_end = None

    def handle_endtag(self, tag):
        if tag == "head" and self.head_end is None:
            self.head_end = self.getpos()
        elif tag == "body":
            self.body_end = self.getpos()


def inject_scripts(source: str, scripts: tuple[str, ...], revision: str = "", session: str = "") -> str:
    parser = _DocumentEnds()
    try:
        parser.feed(source)
        parser.close()
    except AssertionError:
        # Leave malformed declarations for the browser's HTML error recovery.
        pass
    offsets = list(accumulate((len(part) + 1 for part in source.split("\n")), initial=0))

    def index(position):
        if position is None:
            return len(source)
        line, column = position
        return offsets[line - 1] + column

    body = index(parser.body_end)
    includes = "".join(f'<script defer src="{SCRIPT_ROOT}{name}"></script>' for name in scripts)
    if revision:
        meta = f'<meta name="vitruvius-preview-revision" content="{escape(revision, quote=True)}">'
        if session:  # which opening of the preview this page came from: it outlives the live refresh, a stop and a new start changes it
            meta += f'<meta name="vitruvius-preview-session" content="{escape(session, quote=True)}">'
        head = index(parser.head_end)
        if head < body:
            return source[:head] + meta + source[head:body] + includes + source[body:]
        includes = meta + includes
    return source[:body] + includes + source[body:]


class PreviewProxy:
    def __init__(self, host_port: int):
        self.backend: tuple[int, str] | None = None
        self.session = uuid.uuid4().hex[:16]  # one per opening of the preview (the proxy lives until it is stopped)
        self.voice_revision = ""
        voice = self.voice = TransferVoice()
        scripts = {"app-bridge.js": BRIDGE_JS.encode("utf-8")}
        for name in PREVIEW_SCRIPTS:
            path = SCRIPT_DIR / name
            if path.is_file():
                scripts[name] = path.read_bytes()
        parents = (*DEV_ORIGINS, f"http://127.0.0.1:{host_port}", f"http://localhost:{host_port}",
                   f"http://[::1]:{host_port}")
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def respond(self, status, body, content_type, headers=()):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "origin")
                for key, value in headers:
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def stream_reply(self, body):
                started = False
                try:
                    with voice.reply(body) as reply:
                        self.send_response(200)
                        self.send_header("Content-Type", NDJSON)
                        self.send_header("X-Content-Type-Options", "nosniff")
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("X-Transfer-Voice-Engine", reply.engine)
                        self.send_header("X-Transfer-Voice-Job", reply.job_id)
                        started = True
                        self.end_headers()
                        for chunk in reply.chunks:
                            self.wfile.write(chunk)
                except ReplyError as error:
                    if not started:
                        self.respond(*_json(error.status, code=error.code))
                except OSError:
                    pass  # the browser can leave while synthesis is still running

            def forward(self):
                headers = {key.lower(): value for key, value in self.headers.items()}
                port = self.server.server_port
                if verdict := check_request(self.command, headers, port, strict_ports=True,
                                            dev_origins=(), faustus_origins=parents):
                    status, message = verdict
                    return self.respond(status, message.encode("utf-8"), "text/plain; charset=utf-8")
                if (headers.get("sec-fetch-dest") in ("iframe", "frame")
                        and headers.get("sec-fetch-mode") == "navigate"):
                    referer = headers.get("referer", "")
                    parent = urlsplit(referer)
                    if f"{parent.scheme}://{parent.netloc}" not in (*parents, proxy.url):
                        return self.respond(403, b"Preview parent not allowed", "text/plain")
                if not self.path.startswith("/") or self.path.startswith("//"):
                    return self.respond(400, b"Invalid preview path", "text/plain")
                parts = urlsplit(self.path)
                path = parts.path
                backend = proxy.backend
                if backend is None:
                    return self.respond(503, b"Preview is not running", "text/plain")
                if path.startswith(VOICE_PREFIX) and proxy.voice_revision == backend[1]:
                    route = path.removeprefix(VOICE_PREFIX)
                    try:
                        size = int(headers.get("content-length", "0"))
                        if not 0 <= size <= voice.max_body(route):
                            raise ValueError
                    except ValueError:
                        return self.respond(413, b'{"code":"invalid_voice_size"}', "application/json")
                    body = self.rfile.read(size) if size else b""
                    if self.command == "POST" and route == "reply":
                        return self.stream_reply(body)
                    return self.respond(*voice.handle(self.command, route, parts.query,
                                                      headers.get("content-type", ""), body))
                if path.startswith(SCRIPT_ROOT) and self.command == "GET":
                    script = scripts.get(path.removeprefix(SCRIPT_ROOT))
                    if script is None:
                        return self.respond(404, b"Preview script not found", "text/plain")
                    return self.respond(200, script, "text/javascript; charset=utf-8")
                backend_port, revision = backend
                try:
                    size = int(headers.get("content-length", "0"))
                    if size < 0:
                        raise ValueError
                    body = self.rfile.read(size) if size else None
                except ValueError:
                    return self.respond(400, b"Invalid request length", "text/plain")
                forwarded = {key: headers[key] for key in ("content-type", "cookie", "accept", "range", "idempotency-key")
                             if key in headers}
                try:
                    with closing(HTTPConnection("127.0.0.1", backend_port, timeout=15)) as upstream:
                        upstream.request(self.command, self.path, body=body, headers=forwarded)
                        response = upstream.getresponse()
                        payload = response.read()
                except (OSError, HTTPException):
                    return self.respond(502, b"Preview process unavailable", "text/plain")
                content_type = response.headers.get("Content-Type", "application/octet-stream")
                if self.command == "GET" and response.headers.get_content_type() == "text/html":
                    charset = response.headers.get_content_charset() or "utf-8"
                    try:
                        payload = inject_scripts(payload.decode(charset), tuple(scripts), revision, proxy.session).encode(charset)
                    except (UnicodeError, LookupError):
                        pass
                extra = [(key, value) for key, value in response.headers.items() if key.lower() in {
                    "content-security-policy", "content-disposition", "content-range",
                    "x-frame-options", "set-cookie",
                }]
                extra.append(("X-Vitruvius-Revision", revision))
                extra.append(("X-Vitruvius-Session", proxy.session))
                if location := response.headers.get("Location"):
                    location = re.sub(rf"^http://127\.0\.0\.1:{backend_port}(?=/|$)", proxy.url, location)
                    extra.append(("Location", location))
                self.respond(response.status, payload, content_type, extra)

            do_GET = forward
            do_POST = forward
            do_PATCH = forward
            do_DELETE = forward
            do_PUT = forward

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.05}, daemon=True, name="app-preview")
        self.thread.start()

    def close(self) -> None:
        self.backend = None
        self.voice.replies.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
