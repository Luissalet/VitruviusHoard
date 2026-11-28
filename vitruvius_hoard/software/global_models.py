"""Consumer of Faustus' stateless, exactly pinned global-model contract (#938).

Provider credentials never leave Faustus. Missing/stale global selection is an
error; the incorporated SDK's model registry and loopback fallbacks are bypassed.
"""
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from functools import wraps
from concurrent.futures import Future
import asyncio
import threading
import time
import httpx
from hoard_link import Link, LinkConfig, where
from hoard_link._sync import SyncFacade
from hoard_link.types import Resolution
from .owned_http import OwnedAsyncClient,close_client

_job = ContextVar('vitruvius_global_job', default=None)
VISION_RESOLUTION_TIMEOUT_S = 6.0
SPARK_HEALTH_TIMEOUT_S = 3.0
_DEFAULT_FAUSTUS_URLS = LinkConfig().faustus_urls


class VisionUnavailable(ValueError):
    def __init__(self, reason, message, model=None):
        super().__init__(message)
        self.reason = reason
        self.model = model


class VisionTimeout(TimeoutError):
    def __init__(self, model):
        super().__init__("The selected vision model exceeded the model budget.")
        self.model = model


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
    def __init__(self,link):
        super().__init__(link)
        self._close_lock=threading.Lock()

    def _twin(self):
        with self._start_lock:
            if self._inner is None:
                parent = self._link
                self._inner = GlobalLink(parent.config, client=None if parent._owns_client else parent._client)
            return self._inner

    def vision_chat(self, messages, *, images, effort, timeout=None, max_tokens=None):
        return self._run(lambda link: link.vision_chat(
            messages, images=images, effort=effort, timeout=timeout, max_tokens=max_tokens))

    def close(self, timeout=None):
        if self._thread is threading.current_thread():
            raise RuntimeError('Close the global client from its owning module')
        with self._close_lock:
            loop,inner,thread=self._loop,self._inner,self._thread
            if loop is not None:
                async def drain():
                    if inner is not None and inner._owns_client:
                        await close_client(inner._client)
                    if self._link._owns_client:
                        await close_client(self._link._client)
                    await loop.shutdown_asyncgens()
                    await loop.shutdown_default_executor()
                asyncio.run_coroutine_threadsafe(drain(),loop).result()
                loop.call_soon_threadsafe(loop.stop)
            elif self._link._owns_client:
                asyncio.run(close_client(self._link._client))
            if thread is not None:thread.join()
            if loop is not None:loop.close()
            self._loop=self._thread=self._inner=None


class GlobalLink(Link):
    def __init__(self, config, client=None):
        super().__init__(config,OwnedAsyncClient(trust_env=False) if client is None else client)
        self._owns_client=client is None
        self.sync = GlobalSync(self)

    async def aclose(self):
        await asyncio.to_thread(self.sync.close)

    async def status(self, task=None):
        with global_job():
            selected = await self.resolve('llm')
            return {'llm': selected.to_dict()}

    async def selection(self, *, deadline=None):
        pinned = _job.get()
        urls = tuple(self.config.faustus_urls)
        if not urls:
            raise ValueError('Global model unavailable: no configured Faustus endpoint')
        if pinned is None:
            return await self._selection(urls, deadline)
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
            selected = await self._selection(urls, deadline)
        except asyncio.CancelledError:
            # An expired owner must not cancel the other users of its selection.
            future.set_exception(TimeoutError("Global model resolution was cancelled"))
            raise
        except BaseException as error:
            future.set_exception(error)
            raise
        future.set_result(selected)
        return selected

    async def _origin(self, urls, deadline):
        if urls != _DEFAULT_FAUSTUS_URLS:
            return await asyncio.to_thread(self.config.faustus_origin)
        # The SDK appends the active Spark placement after the local candidates.
        candidates = await asyncio.to_thread(self.config.faustus_candidates)
        local, spark = candidates[:len(urls)], candidates[len(urls):]
        token = self.config.faustus_token or ""
        if spark and deadline is not None:
            # Leave at least 40% of the remaining resolution time for local health and the descriptor.
            remaining = deadline - asyncio.get_running_loop().time()
            wait = min(SPARK_HEALTH_TIMEOUT_S, max(0.0, remaining) * 0.6)
            try:
                async with asyncio.timeout(wait):
                    base = await asyncio.to_thread(where.reachable, spark, token=token,
                                                   timeout=SPARK_HEALTH_TIMEOUT_S, remote_timeout=SPARK_HEALTH_TIMEOUT_S)
            except TimeoutError:
                base = ""
            if base:
                return base
            spark = []
        return await asyncio.to_thread(where.reachable, spark + local, token=token) or urls[0]

    async def _selection(self, urls, deadline):
        base = await self._origin(urls, deadline)
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

    async def resolve(self, capability, task=None, *, deadline=None):
        if capability not in ('llm', 'vision'):
            return await super().resolve(capability, task)
        selected = await self.selection(deadline=deadline)
        if capability == 'vision' and not selected['vision']:
            raise VisionUnavailable("no_model", "The selected global model does not expose vision.")
        return Resolution(capability=capability, provider='openai', api='openai', state='resolved',
                          url=selected['base'] + selected['chat_path'], model=selected['model'],
                          reason='Exact global selection through Faustus', details={'allow_load': False})

    async def vision_chat(self, messages, *, images, effort, timeout=None, max_tokens=None):
        """Resolve vision within a short budget and keep the selected model pinned for generation."""
        if not self.config.faustus_urls:
            raise VisionUnavailable("no_model", "No global model endpoint is configured.")

        deadline = time.monotonic() + timeout if timeout is not None else None
        resolution_budget = VISION_RESOLUTION_TIMEOUT_S if timeout is None else min(timeout, VISION_RESOLUTION_TIMEOUT_S)
        with global_job() if _job.get() is None else nullcontext():
            try:
                async with asyncio.timeout(resolution_budget) as resolution_timeout:
                    resolution = await self.resolve("vision", deadline=resolution_timeout.when())
            except VisionUnavailable:
                raise
            except (TimeoutError, httpx.TimeoutException) as error:
                raise VisionUnavailable("resolution_timeout", "Vision model resolution exceeded its budget.") from error
            except (ValueError, httpx.HTTPError) as error:
                raise VisionUnavailable("resolution_error", "The global vision model could not be resolved.") from error

            try:
                remaining = deadline - time.monotonic() if deadline is not None else None
                if remaining is not None and remaining <= 0:
                    raise TimeoutError("The model budget is exhausted")
                return await self.chat(messages, images=images, effort=effort, capability="vision",
                                       timeout=remaining, max_tokens=max_tokens)
            except (TimeoutError, httpx.TimeoutException) as error:
                raise VisionTimeout(resolution.model) from error
            except (ValueError, httpx.HTTPError) as error:
                raise VisionUnavailable("model_error", "The selected vision model could not finish its response.",
                                        model=resolution.model) from error

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
