"""Redis-backed latest tick cache (FR-1.4)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import redis.asyncio as aioredis


def _key(symbol: str) -> str:
    return f"cryptobot:tick:{symbol.upper()}"


class TickCache:
    def __init__(self, redis_url: str) -> None:
        self._redis = aioredis.from_url(redis_url, decode_responses=True)

    async def set_trade(self, symbol: str, price: str, qty: str) -> None:
        payload = json.dumps({
            "price": price, "qty": qty,
            "at": datetime.now(UTC).isoformat(),
        })
        await self._redis.set(_key(symbol), payload, ex=3600)

    async def get(self, symbol: str) -> dict | None:
        raw = await self._redis.get(_key(symbol))
        if raw is None:
            return None
        return json.loads(raw)

    async def close(self) -> None:
        await self._redis.aclose()
