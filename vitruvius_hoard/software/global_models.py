"""Consumer of Faustus' stateless, exactly pinned global-model contract (#938).

Provider credentials never leave Faustus. Missing/stale global selection is an
error; the incorporated SDK's model registry and loopback fallbacks are bypassed.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from concurrent.futures import Future
import asyncio
import threading
import httpx
from hoard_link import Link
from hoard_link._sync import SyncFacade
from hoard_link.types import Resolution

_job = ContextVar('vitruvius_global_job', default=None)


@contextmanager
def global_job():
    token = _job.set({'lock': threading.Lock(), 'selections': {}})
    try:
        yield
    finally:
        _job.reset(token)


def job(function):
    @wraps(function)
    def run(*args, **kwargs):
        with global_job():
            return function(*args, **kwargs)
    return run


class GlobalSync(SyncFacade):
    def _twin(self):
        with self._start_lock:
            if self._inner is None:
                parent = self._link
                self._inner = GlobalLink(parent.config, client=None if parent._owns_client else parent._client)
            return self._inner

    def close(self, timeout=None):
        loop, inner, thread = self._loop, self._inner, self._thread
        if thread is threading.current_thread():
            raise RuntimeError('Close the global client from its owning module')
        if loop is not None:
            if inner is not None and inner._owns_client:
                asyncio.run_coroutine_threadsafe(inner._client.aclose(), loop).result()
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join()
        if loop is not None:
            loop.close()
        self._loop = self._thread = self._inner = None


class GlobalLink(Link):
    def __init__(self, config, client=None):
        super().__init__(config, client)
        self.sync = GlobalSync(self)

    async def aclose(self):
        await asyncio.to_thread(self.sync.close)
        if self._owns_client:
            await self._client.aclose()

    async def status(self, task=None):
        with global_job():
            selected = await self.resolve('llm')
            return {'llm': selected.to_dict()}

    async def selection(self):
        pinned = _job.get()
        urls = tuple(self.config.faustus_urls)
        if not urls:
            raise ValueError('Global model unavailable: no configured Faustus endpoint')
        if pinned is None:
            return await self._selection(urls)
        key = (urls, self.config.faustus_token)
        # A job may resolve concurrently across native threads and event loops.
        # Lock only publication of its one future, never the HTTP request/chat.
        with pinned['lock']:
            future = pinned['selections'].get(key)
            owner = future is None
            if owner:
                future = pinned['selections'][key] = Future()
        if not owner:
            return await asyncio.shield(asyncio.wrap_future(future))
        try:
            selected = await self._selection(urls)
        except BaseException as error:
            future.set_exception(error)
            raise
        future.set_result(selected)
        return selected

    async def _selection(self, urls):
        base = urls[0].rstrip('/')
        headers = {'Authorization': 'Bearer ' + self.config.faustus_token} if self.config.faustus_token else {}
        response = await self._client.get(base + '/api/global-model', headers=headers)
        response.raise_for_status()
        value = response.json()
        for field in ('endpoint_id', 'model'):
            if not isinstance(value.get(field), str) or not value[field]:
                raise ValueError('Global model unavailable: missing ' + field)
        if not isinstance(value.get('connection_revision'), str):
            raise ValueError('Global model unavailable: missing connection revision')
        if value.get('chat_path') != '/api/global-model/v1/chat/completions':
            raise ValueError('Global model contract unavailable')
        selected = {k: value[k] for k in ('endpoint_id', 'model', 'connection_revision', 'chat_path')}
        selected.update(base=base, headers=headers, vision=bool(value.get('vision')))
        return selected

    async def resolve(self, capability, task=None):
        if capability not in ('llm', 'vision'):
            return await super().resolve(capability, task)
        selected = await self.selection()
        if capability == 'vision' and not selected['vision']:
            raise ValueError('The selected global model does not expose vision')
        return Resolution(capability=capability, provider='openai', api='openai', state='resolved',
                          url=selected['base'] + selected['chat_path'], model=selected['model'],
                          reason='Exact global selection through Faustus', details={'allow_load': False})

    async def _post_chat(self, provider, url, payload, level):
        selected = await self.selection()
        if payload.get('model') != selected['model']:
            raise ValueError('Global model changed during job; read selection before starting another job')
        expected = {'expected_' + key: selected[key] for key in ('endpoint_id', 'model', 'connection_revision')}
        response = await self._client.post(selected['base'] + selected['chat_path'],
                                           json={**payload, **expected}, headers=selected['headers'],
                                           timeout=httpx.Timeout(None, connect=15))
        response.raise_for_status()
        choices = response.json().get('choices')
        if not choices or choices[0].get('finish_reason') != 'stop':
            raise ValueError('Global generation did not complete normally')
        return response
