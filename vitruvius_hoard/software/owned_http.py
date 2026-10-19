"""Retain owned HTTP resources when a lower-level close fails."""
import asyncio
import httpx
from httpx._client import ClientState


class OwnedAsyncClient(httpx.AsyncClient):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self._close_pending=None
        self._owner_loop=None

    async def send(self,*args,**kwargs):
        self._owner_loop=asyncio.get_running_loop()
        return await super().send(*args,**kwargs)

    async def aclose(self):
        if self._close_pending is None:
            resources=[]
            for transport in [self._transport,*self._mounts.values()]:
                if transport is not None:
                    pool=getattr(transport,'_pool',None)
                    resources.extend((connection,pool) for connection in getattr(pool,'_connections',()))
                    resources.append((transport,None))
            seen=set()
            self._close_pending=[]
            for resource,pool in resources:
                if id(resource) not in seen:
                    seen.add(id(resource))
                    self._close_pending.append((resource,pool))
        # Prevent new sends while retaining every unsuccessful physical close.
        self._state=ClientState.CLOSED
        while self._close_pending:
            resource,pool=self._close_pending[0]
            await resource.aclose()
            if pool is not None:
                with pool._optional_thread_lock:
                    pool._connections=[item for item in pool._connections if item is not resource]
            self._close_pending.pop(0)


async def close_client(client):
    owner=getattr(client,'_owner_loop',None)
    if owner is not None and owner is not asyncio.get_running_loop() and owner.is_running():
        await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(client.aclose(),owner))
    else:
        await client.aclose()
