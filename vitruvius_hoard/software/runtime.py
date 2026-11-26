"""One async owner per native module. OFF is reported only after requests and resources finish."""
import asyncio
import json
import os
from pathlib import Path
from ..hoard_link.atomic import read_json, write_json_atomic
from .cancellation import join_tasks, owned

ROOT = Path(__file__).resolve().parents[2]


def profile():
    configured = os.environ.get("VITRUVIUS_PROFILE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    # Editable checkouts keep their existing default. Installed distributions
    # must never create databases/tokens inside site-packages.
    if (ROOT / '.git').exists():
        return ROOT / 'data'
    base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / '.local/share')
    return (base / 'VitruviusHoard' / 'data').resolve()


def token_path():
    return Path(os.environ.get('VITRUVIUS_TOKEN_FILE') or os.environ.get('HOARD_TOKEN_FILE') or profile() / 'mcp-token')


class Module:
    def __init__(self, name):
        self.name = name
        self.app = None
        self.context = None
        self.context_failed = False
        self.state = "off"
        self.error = None
        self.automatic = False
        self.lock = asyncio.Lock()
        self.active = 0
        self.readers = set()
        self.idle = asyncio.Event()
        self.idle.set()

    async def set(self, enabled, automatic=False):
        return await owned(self._set(enabled, automatic))

    async def _set(self, enabled, automatic):
        async with self.lock:
            return await self._transition(enabled, automatic)

    async def _transition(self, enabled, automatic):
        if not enabled and self.app is None:
            self.context_failed = False
            self.state = "off"
            self.error = None
            self.automatic = automatic
            return self.status()
        if enabled and self.state == "on":
            if self.name == 'design':
                self.app.state.services.config.embed_auto = automatic
            self.automatic = automatic
            return self.status()
        if enabled and self.app is not None:
            raise ValueError('Close the retained owner successfully before enabling it again')

        try:
            if enabled:
                self.state = "starting"
                self.automatic = automatic
                self.app = await asyncio.to_thread(self.create)
                self.context = self.app.router.lifespan_context(self.app)
                await self.context.__aenter__()
                self.state = "on"
            else:
                self.state = "stopping"
                await join_tasks(list(self.readers), cancel=True)
                await self.idle.wait()
                if self.context_failed:
                    from .cleanup import invoke
                    shutdown = getattr(self.app.state, 'shutdown', None)
                    if shutdown is None:
                        raise RuntimeError('Failed lifespan has no retryable shutdown; owner remains retained')
                    await invoke(shutdown)
                else:
                    await self.context.__aexit__(None, None, None)
                self.app = self.context = None
                self.state = "off"
        except BaseException as exc:
            self.context_failed = True
            self.state = "error"
            self.error = str(exc) or type(exc).__name__
            raise
        self.context_failed = False
        self.error = None
        self.automatic = automatic
        return self.status()

    def create(self):
        from .native import create_native
        return create_native(self.name, self.automatic)

    def status(self):
        status = {"module": self.name, "state": self.state, "enabled": self.state == "on",
                  "automatic": self.automatic, "active_requests": self.active}
        if self.error is not None:
            status["error"] = self.error
        return status

    async def __call__(self, scope, receive, send):
        if self.state != "on":
            from starlette.responses import JSONResponse
            await JSONResponse({"error": "Module is " + self.state, "module": self.name,
                                "controls": "/"}, status_code=409)(scope, receive, send)
            return
        self.active += 1
        self.idle.clear()
        task = None
        # Shape only the native copilot's own known contract; native API/media
        # bytes pass through untouched, including Range and streaming bodies.
        start, chunks = None, []
        scoped = False
        async def forward(message):
            nonlocal start, scoped
            if message['type'] == 'http.response.start':
                start = message
                headers = dict(message.get('headers', []))
                scoped = (b'text/html' in headers.get(b'content-type', b'') and '/api/' not in str(scope['path'])) or str(scope['path']).endswith(('/api/copilot/launcher.js', '/api/copilot/info', '/manifest.webmanifest', '/sw.js'))
                if not scoped:
                    await send(message)
            elif message['type'] == 'http.response.body' and scoped:
                chunks.append(message.get('body', b''))
                if not message.get('more_body'):
                    body = b''.join(chunks)
                    prefix = '/' + self.name
                    import re
                    if not str(scope['path']).endswith(('/api/copilot/info','/manifest.webmanifest')):
                        body = re.sub(rb'(?<=["\'`])/(api/(?!software/)|static/|assets/)', lambda m: prefix.encode() + b'/' + m[1], body)
                    if str(scope['path']).endswith('/api/copilot/info'):
                        info = json.loads(body)
                        # The panel's server is the remote Faustus API root;
                        # only its local relay/panel URL belongs to this module.
                        info.update(tool_server_id='vitruvius', server='/')
                        if info.get('panel_url','').startswith('/api/'):
                            info['panel_url'] = prefix + info['panel_url']
                        body = json.dumps(info).encode()
                    if str(scope['path']).endswith('/manifest.webmanifest'):
                        manifest = json.loads(body)
                        manifest.update(start_url=prefix + '/', scope=prefix + '/')
                        for icon in manifest.get('icons', []):
                            if icon['src'].startswith('/') and not icon['src'].startswith(prefix + '/'):
                                icon['src'] = prefix + icon['src']
                        body = json.dumps(manifest).encode()
                    if str(scope['path']).endswith('/sw.js'):
                        body = body.replace(b'"/api/"', (f'"{prefix}/api/"').encode()).replace(b'"/assets/"', (f'"{prefix}/assets/"').encode())
                        body = body.replace(b'name !== CACHE_NAME', b'name.startsWith("vitruvius-") && name !== CACHE_NAME')
                    headers = [(k,v) for k,v in start.get('headers', []) if k.lower() not in (b'content-length', b'etag')]
                    await send({**start, 'headers': headers + [(b'content-length', str(len(body)).encode())]})
                    await send({'type': 'http.response.body', 'body': body})
            else:
                await send(message)
        try:
            from .global_models import global_job
            with global_job():
                task = asyncio.create_task(self.app(scope, receive, forward))
                if scope.get('method') in ('GET', 'HEAD'):
                    self.readers.add(task)
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    await join_tasks([task], cancel=scope.get('method') in ('GET', 'HEAD'))
                    raise
        finally:
            self.readers.discard(task)
            self.active -= 1
            if not self.active:
                self.idle.set()


class Runtime:
    def __init__(self):
        self.modules = {k: Module(k) for k in ("design", "babel", "theseus")}
        self.settings = {}

    async def restore(self):
        self.settings.clear()
        saved = read_json(profile() / "software-modules.json")
        if not isinstance(saved, dict) or type(saved.get("version")) is not int or saved["version"] != 1:
            return
        settings = saved.get("modules")
        if not isinstance(settings, dict):
            return
        for name, module in self.modules.items():
            setting = settings.get(name)
            if not isinstance(setting, dict) or any(
                type(setting.get(key)) is not bool for key in ("enabled", "automatic")
            ):
                continue
            self.settings[name] = {key: setting[key] for key in ("enabled", "automatic")}
            try:
                await module.set(**self.settings[name])
            except Exception:
                # The failed owner reports its error. Continue restoring the others.
                continue

    async def set_module(self, name, enabled, automatic=False):
        return await owned(self._set_module(name, enabled, automatic))

    async def _set_module(self, name, enabled, automatic):
        module = self.modules[name]
        async with module.lock:
            previous = self.settings.get(name, {"enabled": module.state == "on", "automatic": module.automatic})
            settings = {**self.settings, name: {"enabled": enabled, "automatic": automatic}}
            try:
                # Commit intent before touching the owner. No await between reading and replacing
                # the settings, so updates to independent modules cannot overwrite each other.
                write_json_atomic(profile() / "software-modules.json", {"version": 1, "modules": settings})
            except OSError as exc:
                raise NativeError(500, {"error": f"Could not save software module settings: {exc}"}) from exc
            self.settings = settings
            status = await module._transition(enabled, automatic)
            return {**status, "previous": previous}

    def status(self):
        return {"modules": [m.status() for m in self.modules.values()]}

    async def call(self, name, arguments, *, admitted=False, agent=''):
        import httpx
        catalog = json.loads(Path(__file__).with_name('catalog.json').read_text(encoding='utf8'))
        entry = next((row for row in catalog if row['name'] == name), None)
        if not entry:
            raise ValueError('Unknown tool: ' + name)
        owner = self.modules[entry['module']]
        if owner.state != 'on' and not (admitted and owner.state == 'stopping' and owner.app is not None):
            raise ValueError('Enable module explicitly first: ' + owner.name)
        owner.active += 1
        owner.idle.clear()
        try:
            token = (profile()/owner.name/'mcp-token').read_text(encoding='utf8').strip()
            path = '/api/agent/' + name if owner.name == 'babel' else '/api/agent/call'
            payload = arguments if owner.name == 'babel' else {'tool' if owner.name=='theseus' else 'name':name, 'arguments':arguments}
            if agent:
                payload['agent'] = agent
            from .native import port
            from .global_models import global_job
            with global_job():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=owner.app), base_url='http://127.0.0.1:'+str(port()),timeout=None) as client:
                    response = await owned(client.post(path,json=payload,headers={'Authorization':'Bearer '+token}))
            if response.is_error:
                raise NativeError(response.status_code, response.json())
            return response.json()
        finally:
            owner.active -= 1
            if not owner.active:
                owner.idle.set()

    async def close(self):
        await asyncio.gather(*(m.set(False) for m in self.modules.values()))


class NativeError(Exception):
    def __init__(self, status, body):
        super().__init__(str(body))
        self.status, self.body = status, body
    def to_dict(self):
        return self.body
