"""Owned transitions and native jobs finish before their cancelled waiter returns."""
import asyncio
import anyio


async def join_tasks(tasks, *, cancel=False):
    tasks = list(dict.fromkeys(tasks))
    if cancel:
        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()
    joined = asyncio.gather(*tasks, return_exceptions=True)
    interrupted = False
    with anyio.CancelScope(shield=True):
        while True:
            try:
                result = await asyncio.shield(joined)
                break
            except asyncio.CancelledError:
                interrupted = True
    if interrupted:
        raise asyncio.CancelledError
    return result


async def owned(awaitable):
    task = asyncio.create_task(awaitable)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await join_tasks([task])
        raise
