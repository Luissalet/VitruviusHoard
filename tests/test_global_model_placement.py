import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

DESCRIPTOR = dict(endpoint_id='sparks-a', model='spark-model', connection_revision='r1',
                  chat_path='/api/global-model/v1/chat/completions', protocol='openai', vision=True)


def _serve(routes):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            body = routes.get(self.path)
            self.send_response(200 if body is not None else 404)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(body if body is not None else {}).encode())
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def spark_placement():
    """Faustus answering on a "Spark", a Hub that says so, and a dead PC address. Yields (spark_url, hub_url, dead_url)."""
    faustus = _serve({'/api/health': {'status': 'healthy'}, '/api/global-model': DESCRIPTOR})
    spark = f'http://127.0.0.1:{faustus.server_port}'
    hub = _serve({'/api/placement': {'location': 'sparks', 'job': {'running': False}, 'urls': {'faustus': spark}}})
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        dead = f'http://127.0.0.1:{sock.getsockname()[1]}'
    try:
        yield spark, f'http://127.0.0.1:{hub.server_port}', dead
    finally:
        for server in (faustus, hub):
            server.shutdown()
            server.server_close()


@pytest.mark.asyncio
async def test_global_link_selection_follows_faustus_to_the_spark(spark_placement):
    from vitruvius_hoard.software.global_models import GlobalLink
    from vitruvius_hoard.hoard_link import where
    from vitruvius_hoard.hoard_link.config import LinkConfig
    spark, hub, dead = spark_placement
    where.forget()
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json=DESCRIPTOR)

    link = GlobalLink(LinkConfig(faustus_urls=(dead,), hub_url=hub), client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        chosen = await link.selection()
    finally:
        await link.aclose()
        where.forget()
    assert seen == [spark + '/api/global-model']
    assert chosen['base'] == spark and chosen['model'] == 'spark-model' and chosen['vision'] is True