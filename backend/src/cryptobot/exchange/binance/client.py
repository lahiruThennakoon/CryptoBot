"""Low-level Binance Spot REST client.

Endpoints verified against the official binance/binance-spot-api-docs
repository (testnet/general-info.md and rest-api docs). Base URLs:
  Testnet: https://testnet.binance.vision/api
  Live:    https://api.binance.com/api

Responsibilities: HMAC-SHA256 signing, server-time sync, client-side rate
limiting, exponential backoff with jitter, 429/418 handling, secret hygiene
(secrets never logged; signed query strings never logged raw).
"""

from __future__ import annotations

import hashlib
import hmac
import random
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from pydantic import SecretStr

from cryptobot.core.logging import get_logger
from cryptobot.exchange.errors import (
    ExchangeApiError,
    ExchangeConnectionError,
    IpBanned,
    RateLimitExceeded,
)
from cryptobot.exchange.rate_limiter import RateLimiter
from cryptobot.exchange.time_sync import TimeSync

logger = get_logger(__name__)

_RETRYABLE_STATUS = {500, 502, 503, 504}


class BinanceRestClient:
    def __init__(
        self,
        base_url: str,
        api_key: SecretStr,
        api_secret: SecretStr,
        rate_limiter: RateLimiter | None = None,
        time_sync: TimeSync | None = None,
        max_retries: int = 5,
        timeout_s: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._api_secret = api_secret
        self.rate_limiter = rate_limiter or RateLimiter()
        self.time_sync = time_sync or TimeSync()
        self._max_retries = max_retries
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout_s,
            headers={"X-MBX-APIKEY": api_key.get_secret_value()},
        )

    async def close(self) -> None:
        await self._client.aclose()

    # ── time sync ────────────────────────────────────────────────────
    async def sync_time(self) -> None:
        t0 = time.monotonic()
        data = await self.request("GET", "/v3/time", weight=1)
        rtt_ms = (time.monotonic() - t0) * 1000
        self.time_sync.update(int(data["serverTime"]), rtt_ms)
        logger.info("time_synced", offset_ms=round(self.time_sync.offset_ms, 1), rtt_ms=round(rtt_ms, 1))

    # ── request core ─────────────────────────────────────────────────
    def _sign(self, params: dict[str, Any]) -> dict[str, Any]:
        params = {k: v for k, v in params.items() if v is not None}
        params["timestamp"] = self.time_sync.timestamp_ms()
        query = urlencode(params)
        signature = hmac.new(
            self._api_secret.get_secret_value().encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        params["signature"] = signature
        return params

    async def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        signed: bool = False,
        weight: int = 1,
        is_order: bool = False,
    ) -> Any:
        """Send a request with rate limiting, retries and backoff.

        IMPORTANT: order submissions (is_order=True) are NEVER retried here.
        On ambiguity the caller must query the order state first (docs/
        risk-policy.md §5 — query-before-retry).
        """
        params = {k: v for k, v in (params or {}).items() if v is not None}
        attempts = 1 if is_order else self._max_retries

        last_error: Exception | None = None
        for attempt in range(attempts):
            await self.rate_limiter.acquire(weight=weight, is_order=is_order)
            send_params = self._sign(dict(params)) if signed else params
            try:
                response = await self._client.request(method, path, params=send_params)
            except httpx.HTTPError as exc:
                last_error = ExchangeConnectionError(f"{method} {path}: {type(exc).__name__}")
                if is_order:
                    raise last_error from exc
                await self._backoff(attempt)
                continue

            if response.status_code == 418:
                raise IpBanned("HTTP 418: IP auto-banned for repeated rate-limit violations")
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", "5"))
                logger.warning("rate_limited", path=path, retry_after_s=retry_after)
                if is_order or attempt == attempts - 1:
                    raise RateLimitExceeded(retry_after)
                await self._sleep(retry_after + random.uniform(0, 1))
                continue
            if response.status_code in _RETRYABLE_STATUS and not is_order:
                last_error = ExchangeApiError(response.status_code, None, "server error")
                await self._backoff(attempt)
                continue
            if response.status_code >= 400:
                body: dict[str, Any] = {}
                try:
                    body = response.json()
                except ValueError:
                    pass
                raise ExchangeApiError(
                    response.status_code, body.get("code"), str(body.get("msg", "unknown"))
                )
            return response.json()

        raise last_error or ExchangeConnectionError(f"{method} {path}: retries exhausted")

    async def _backoff(self, attempt: int) -> None:
        delay = min(2**attempt, 30) + random.uniform(0, 1)  # exponential + jitter
        logger.warning("backing_off", attempt=attempt, delay_s=round(delay, 2))
        await self._sleep(delay)

    @staticmethod
    async def _sleep(seconds: float) -> None:
        import asyncio

        await asyncio.sleep(seconds)
