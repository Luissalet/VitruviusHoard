"""Retryable native shutdown; a failed step remains owned until it succeeds."""
import asyncio
import inspect


async def invoke(callback):
    if inspect.iscoroutinefunction(callback):
        return await callback()
    result = await asyncio.to_thread(callback)
    if inspect.isawaitable(result):
        return await result


class Shutdown:
    def __init__(self, *steps):
        self.steps = steps
        self.completed = 0
        self.lock = asyncio.Lock()

    async def __call__(self):
        async with self.lock:
            while self.completed < len(self.steps):
                await invoke(self.steps[self.completed])
                self.completed += 1
