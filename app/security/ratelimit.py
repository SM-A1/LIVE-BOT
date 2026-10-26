from __future__ import annotations

import asyncio
import time


class Throttle:
    """Fixed-window limiter. Uses Redis when available, in-memory otherwise."""

    def __init__(self, redis=None):
        self._r = redis
        self._mem: dict[str, tuple[float, int]] = {}

    async def hit(self, key: str, limit: int, window: int) -> bool:
        if self._r is not None:
            try:
                n = await self._r.incr(f"rl:{key}")
                if n == 1:
                    await self._r.expire(f"rl:{key}", window)
                return n <= limit
            except Exception:
                pass  # fall back to memory
        now = time.monotonic()
        start, count = self._mem.get(key, (now, 0))
        if now - start >= window:
            start, count = now, 0
        count += 1
        self._mem[key] = (start, count)
        if len(self._mem) > 50_000:
            self._mem = {k: v for k, v in self._mem.items() if now - v[0] < window}
        return count <= limit


class Pacer:
    """Outbound pacing: at most `rate` calls per second."""

    def __init__(self, rate: float):
        self._interval = 1.0 / rate
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self._interval
        if delay > 0:
            await asyncio.sleep(delay)

    def penalize(self, seconds: float) -> None:
        self._next = max(self._next, time.monotonic() + seconds)
