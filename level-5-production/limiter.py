"""NEW in Level 5: a client-side rate limiter.

The server will answer "429 Too Many Requests" if you go too fast, and retrying
makes a burst worse. It is better to never burst. This limiter spaces out the
START of requests, so at most `rate` begin per second, however many are waiting.

Concurrency (how many requests are IN FLIGHT) and rate (how many START per second)
are different limits. Slow requests pile up under concurrency limits. Fast requests
hit rate limits. You usually need both.
"""

import asyncio
import time


class RateLimiter:
    def __init__(self, rate_per_second: float) -> None:
        # 0 or negative means "no limit".
        self._interval = 1.0 / rate_per_second if rate_per_second > 0 else 0.0
        self._lock = asyncio.Lock()
        self._next_start = 0.0
        self.count = 0  # how many requests have been allowed to start

    async def wait(self) -> None:
        self.count += 1
        if self._interval == 0.0:
            return
        async with self._lock:
            now = time.monotonic()
            start = max(now, self._next_start)
            self._next_start = start + self._interval
        delay = start - now
        if delay > 0:
            await asyncio.sleep(delay)