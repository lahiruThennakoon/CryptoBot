"""Operator control state shared between the API and the trading runtime.

Redis-backed so the API container can control the runtime container.
High-risk actions (emergency stop, resume after halt) use a two-step
arm/confirm flow: POST /controls/arm issues a short-lived one-time token
that must accompany the destructive call — the server-side authorization
required by docs/prd.md FR-10.2.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

import redis.asyncio as aioredis

KEY_PAUSED = "cryptobot:control:paused"
KEY_ESTOP = "cryptobot:control:emergency_stop"
KEY_ARM = "cryptobot:control:arm_token"
ARM_TTL_S = 60


@dataclass
class ControlState:
    paused: bool = False
    emergency_stop: bool = False

    @property
    def trading_allowed(self) -> bool:
        return not (self.paused or self.emergency_stop)


class ControlService:
    def __init__(self, redis_url: str) -> None:
        self._redis = aioredis.from_url(redis_url, decode_responses=True)

    async def state(self) -> ControlState:
        paused, estop = await self._redis.mget(KEY_PAUSED, KEY_ESTOP)
        return ControlState(paused=paused == "1", emergency_stop=estop == "1")

    async def pause(self) -> None:
        await self._redis.set(KEY_PAUSED, "1")

    async def resume(self) -> None:
        await self._redis.delete(KEY_PAUSED)

    async def arm(self) -> str:
        """Issue a one-time confirmation token (60s TTL)."""
        token = secrets.token_urlsafe(24)
        await self._redis.set(KEY_ARM, token, ex=ARM_TTL_S)
        return token

    async def confirm(self, token: str) -> bool:
        """Consume the arm token; True only if it matches and was unexpired."""
        stored = await self._redis.getdel(KEY_ARM)
        return bool(stored) and secrets.compare_digest(stored, token)

    async def emergency_stop(self) -> None:
        await self._redis.set(KEY_ESTOP, "1")

    async def clear_emergency_stop(self) -> None:
        await self._redis.delete(KEY_ESTOP)

    async def close(self) -> None:
        await self._redis.aclose()
