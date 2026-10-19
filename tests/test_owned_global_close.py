"""Physical transport failures must retain the actual native module owner."""
import asyncio
import threading
import httpx
import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize('name',['design','babel'])
@pytest.mark.parametrize('parent',[False,True])
async def test_physical_close_retries_before_native_off(tmp_path,monkeypatch,name,parent):
    monkeypatch.setenv('VITRUVIUS_PROFILE_DIR',str(tmp_path))
    monkeypatch.setenv('VITRUVIUS_EMBED','none')
    monkeypatch.setenv('HOARD_EVENTS','0')
    from vitruvius_hoard.software.runtime import Module
    owner=Module(name);await owner.set(True)
    app=owner.app;link=app.state.link if name=='babel' else app.state.services._link
    await asyncio.to_thread(link.sync._run,lambda _:asyncio.sleep(0))
    inner,loop,thread=link.sync._inner,link.sync._loop,link.sync._thread
    client=link._client if parent else inner._client
    entered,release=threading.Event(),threading.Event()
    async def endpoint(scope,receive,send):
        await send({'type':'http.response.start','status':200,'headers':[]})
        await send({'type':'http.response.body','body':b'{}'})
    class Transport(httpx.ASGITransport):
        attempts=0
        open=True
        async def aclose(self):
            self.attempts+=1
            if self.attempts<3:raise OSError('Physical transport still open')
            entered.set()
            await asyncio.to_thread(release.wait)
            self.open=False
    transport=Transport(app=endpoint)
    if parent:await client._transport.aclose()
    else:await asyncio.to_thread(link.sync._run,lambda _:client._transport.aclose())
    client._transport=transport
    if parent:response=await client.get('http://synthetic.invalid/')
    else:response=await asyncio.to_thread(link.sync._run,lambda _:client.get('http://synthetic.invalid/'))
    assert response.status_code==200
    try:
        for n in (1,2):
            with pytest.raises(OSError,match='Physical transport'):await owner.set(False)
            assert transport.attempts==n and transport.open and owner.app is app
            assert link.sync._loop is loop and loop.is_running() and thread.is_alive()
            with pytest.raises(ValueError):await owner.set(True)
        closing=asyncio.create_task(owner.set(False))
        assert await asyncio.to_thread(entered.wait,5)
        closing.cancel();await asyncio.sleep(.01);closing.cancel();await asyncio.sleep(.01)
        assert not closing.done() and owner.app is app and thread.is_alive()
        release.set()
        with pytest.raises(asyncio.CancelledError):await closing
        assert transport.attempts==3 and not transport.open and owner.app is None
        assert loop.is_closed() and not thread.is_alive()
        assert link._client.is_closed and inner._client.is_closed
        await owner.set(False)
        assert transport.attempts==3
    finally:
        release.set()
        transport.attempts=3
        await owner.set(False)


@pytest.mark.asyncio
async def test_pool_does_not_consume_failed_connection_or_repeat_success():
    import httpcore
    from httpcore._async.http11 import AsyncHTTP11Connection
    from httpcore._models import Origin
    from vitruvius_hoard.software.owned_http import OwnedAsyncClient
    class Stream:
        def __init__(self,failures):self.failures,self.attempts,self.open=failures,0,True
        async def aclose(self):
            self.attempts+=1
            if self.attempts<=self.failures:raise OSError('Physical stream still open')
            self.open=False
    client=OwnedAsyncClient(trust_env=False)
    pool=client._transport._pool
    origin=Origin(b'http',b'synthetic.invalid',80)
    good,bad=Stream(0),Stream(2)
    for stream in (good,bad):
        connection=httpcore.AsyncHTTPConnection(origin)
        connection._connection=AsyncHTTP11Connection(origin,stream)
        pool._connections.append(connection)
    for n in (1,2):
        with pytest.raises(OSError):await client.aclose()
        assert good.attempts==1 and not good.open and bad.attempts==n and bad.open
        assert len(pool._connections)==1
    await client.aclose();await client.aclose()
    assert good.attempts==1 and bad.attempts==3 and not bad.open and not pool._connections
