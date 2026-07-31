"""Client-side rate limiting for Binance request weight and order counts.

Defaults follow the published Spot limits (6000 request weight/min per IP,
orders per 10s/day per account); actual limits are read from exchangeInfo at
startup and applied via `configure`. We throttle *before* hitting the server
so 429s are the exception, not the strategy.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class _Window:
    limit: int
    interval_s: float
    events: deque[tuple[float, int]] = field(default_factory=deque)

    def _used(self, now: float) -> int:
        while self.events and self.events[0][0] <= now - self.interval_s:
            self.events.popleft()
        return sum(w for _, w in self.events)

    def wait_time(self, now: float, weight: int) -> float:
        if self._used(now) + weight <= self.limit:
            return 0.0
        # earliest moment enough weight expires
        needed = self._used(now) + weight - self.limit
        freed = 0
        for ts, w in self.events:
            freed += w
            if freed >= needed:
                return max(0.0, ts + self.interval_s - now)
        return self.interval_s

    def record(self, now: float, weight: int) -> None:
        self.events.append((now, weight))


class RateLimiter:
    """Sliding-window limiter for request weight and order submissions."""

    def __init__(
        self,
        request_weight_per_min: int = 6000,
        orders_per_10s: int = 100,
        orders_per_day: int = 200_000,
        safety_factor: float = 0.75,
    ) -> None:
        self._safety = safety_factor
        self._weight = _Window(int(request_weight_per_min * safety_factor), 60.0)
        self._orders_10s = _Window(int(orders_per_10s * safety_factor), 10.0)
        self._orders_day = _Window(int(orders_per_day * safety_factor), 86_400.0)
        self._lock = asyncio.Lock()

    def configure(
        self,
        request_weight_per_min: int | None = None,
        orders_per_10s: int | None = None,
        orders_per_day: int | None = None,
    ) -> None:
        """Apply limits read from exchangeInfo rateLimits."""
        if request_weight_per_min:
            self._weight.limit = int(request_weight_per_min * self._safety)
        if orders_per_10s:
            self._orders_10s.limit = int(orders_per_10s * self._safety)
        if orders_per_day:
            self._orders_day.limit = int(orders_per_day * self._safety)

    async def acquire(self, weight: int = 1, is_order: bool = False) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                waits = [self._weight.wait_time(now, weight)]
                if is_order:
                    waits.append(self._orders_10s.wait_time(now, 1))
                    waits.append(self._orders_day.wait_time(now, 1))
                wait = max(waits)
                if wait <= 0:
                    self._weight.record(now, weight)
                    if is_order:
                        self._orders_10s.record(now, 1)
                        self._orders_day.record(now, 1)
                    return
                await asyncio.sleep(wait)
