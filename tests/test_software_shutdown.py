"""Failed async-generator exit must not release a live native owner."""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
import pytest


@pytest.mark.asyncio
async def test_failed_generic_lifespan_is_retained_without_retry_callback():
    from vitruvius_hoard.software.runtime import Module
    attempts=0
    @asynccontextmanager
    async def lifespan(app):
        nonlocal attempts
        try: yield
        finally:
            attempts+=1
            raise OSError('retained synthetic resource')
    app=FastAPI(lifespan=lifespan)
    owner=Module('synthetic');owner.create=lambda:app
    await owner.set(True)
    for _ in range(3):
        with pytest.raises((OSError,RuntimeError)):await owner.set(False)
        assert owner.app is app and owner.state=='error'
        with pytest.raises(ValueError):await owner.set(True)
    assert attempts==1


@pytest.mark.asyncio
@pytest.mark.parametrize('name',['design','babel','theseus'])
async def test_real_native_factory_two_failures_and_effective_third_off(name,tmp_path,monkeypatch):
    monkeypatch.setenv('VITRUVIUS_PROFILE_DIR',str(tmp_path))
    monkeypatch.setenv('HOARD_EVENTS','0')
    monkeypatch.setenv('VITRUVIUS_EMBED','none')
    from vitruvius_hoard.software.runtime import Module
    owner=Module(name)
    await owner.set(True)
    app=owner.app
    attempts=0
    if name=='babel':
        resource=app.state.link
        original=resource.aclose
        async def close():
            nonlocal attempts
            attempts+=1
            if attempts<3:raise OSError('retained native link')
            await original()
        monkeypatch.setattr(resource,'aclose',close)
        opened=lambda:not resource._client.is_closed
    else:
        resource=app.state.services.browser if name=='design' else app.state.comparisons.pool
        method='stop' if name=='design' else 'shutdown'
        original=getattr(resource,method)
        def close(*args,**kwargs):
            nonlocal attempts
            attempts+=1
            if attempts<3:raise OSError('retained native cleanup')
            return original(*args,**kwargs)
        monkeypatch.setattr(resource,method,close)
        opened=lambda: not resource._shutdown if name=='theseus' else app.state.services._stop_completed<7
    for expected in (1,2):
        with pytest.raises(OSError):await owner.set(False)
        assert owner.app is app and owner.state=='error' and attempts==expected and opened()
        with pytest.raises(ValueError):await owner.set(True)
        assert owner.app is app and attempts==expected
    await owner.set(False)
    assert attempts==3 and owner.app is None and owner.state=='off' and not opened()
    await owner.set(False)
    assert attempts==3
    await owner.set(True)
    assert owner.app is not app
    await owner.set(False)


@pytest.mark.asyncio
async def test_retry_cleanup_keeps_successful_steps_and_survives_caller_cancel():
    from vitruvius_hoard.software.cleanup import Shutdown
    from vitruvius_hoard.software.runtime import Module
    entered,release=asyncio.Event(),asyncio.Event()
    calls=[]
    async def first():calls.append('first')
    async def last():
        calls.append('last')
        if calls.count('last')<3:raise OSError('held')
        entered.set();await release.wait()
    app=FastAPI()
    app.state.shutdown=Shutdown(first,last)
    @asynccontextmanager
    async def lifespan(app):
        try:yield
        finally:await app.state.shutdown()
    app.router.lifespan_context=lifespan
    owner=Module('synthetic');owner.create=lambda:app
    await owner.set(True)
    for _ in range(2):
        with pytest.raises(OSError):await owner.set(False)
    closing=asyncio.create_task(owner.set(False))
    await entered.wait();closing.cancel();closing.cancel()
    await asyncio.sleep(0)
    assert not closing.done() and owner.app is app and owner.state=='stopping'
    release.set()
    await asyncio.gather(closing,return_exceptions=True)
    assert calls==['first','last','last','last'] and owner.state=='off'
