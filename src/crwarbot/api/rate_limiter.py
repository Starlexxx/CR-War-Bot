from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Combined token-bucket (per-second rate) + semaphore (concurrency).

    Both gates are satisfied for every acquisition.
    """

    def __init__(self, rate_per_sec: float, max_concurrent: int) -> None:
        self._rate = float(rate_per_sec)
        self._sem = asyncio.Semaphore(max_concurrent)
        self._tokens = 1.0
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> RateLimiter:
        await self._sem.acquire()
        await self._await_token()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._sem.release()

    async def _await_token(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(self._rate, self._tokens + elapsed * self._rate)
                self._last_refill = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
            await asyncio.sleep(wait)
