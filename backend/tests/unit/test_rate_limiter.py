import asyncio
import time

from cryptobot.exchange.rate_limiter import RateLimiter


class TestRateLimiter:
    async def test_within_budget_no_wait(self):
        limiter = RateLimiter(request_weight_per_min=6000)
        start = time.monotonic()
        for _ in range(10):
            await limiter.acquire(weight=1)
        assert time.monotonic() - start < 0.5

    async def test_over_budget_throttles(self):
        # Tiny budget: 4 effective weight (safety 0.75 on 5 declared) per 0.2s window
        limiter = RateLimiter(request_weight_per_min=5)
        limiter._weight.interval_s = 0.2  # shrink window for test speed
        start = time.monotonic()
        for _ in range(5):
            await limiter.acquire(weight=1)
        assert time.monotonic() - start >= 0.15  # 5th call had to wait for the window

    async def test_order_counter_separate_from_weight(self):
        limiter = RateLimiter(orders_per_10s=2)
        limiter._orders_10s.interval_s = 0.2
        start = time.monotonic()
        await limiter.acquire(is_order=True)
        await limiter.acquire(is_order=True)  # 2nd order: budget is int(2*0.75)=1 → waits
        assert time.monotonic() - start >= 0.15

    async def test_concurrent_acquires_serialize_safely(self):
        limiter = RateLimiter(request_weight_per_min=6000)
        await asyncio.gather(*(limiter.acquire(weight=1) for _ in range(50)))
