"""BinanceRestClient behavior tests with mocked HTTP (respx)."""

import time

import httpx
import pytest
import respx
from pydantic import SecretStr


def _now_ms() -> int:
    """Mocked server time must track the real clock, or the drift guard
    (correctly) rejects the signed request."""
    return int(time.time() * 1000)

from cryptobot.exchange.binance.client import BinanceRestClient
from cryptobot.exchange.errors import (
    ExchangeApiError,
    ExchangeConnectionError,
    RateLimitExceeded,
)

BASE = "https://testnet.binance.vision/api"


def _client(**kwargs) -> BinanceRestClient:
    return BinanceRestClient(
        base_url=BASE,
        api_key=SecretStr("test-api-key-0123456789abcdef"),
        api_secret=SecretStr("test-api-secret-0123456789abcdef"),
        max_retries=3,
        **kwargs,
    )


@respx.mock
async def test_signed_request_includes_signature_and_timestamp():
    respx.get(f"{BASE}/v3/time").mock(
        return_value=httpx.Response(200, json={"serverTime": _now_ms()})
    )
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(httpx.QueryParams(request.url.query))
        return httpx.Response(200, json={"balances": []})

    respx.get(f"{BASE}/v3/account").mock(side_effect=handler)

    client = _client()
    await client.sync_time()
    await client.request("GET", "/v3/account", signed=True)
    await client.close()

    assert "signature" in captured["params"]
    assert "timestamp" in captured["params"]
    assert len(captured["params"]["signature"]) == 64  # HMAC-SHA256 hex


@respx.mock
async def test_429_raises_rate_limit_after_retries():
    respx.get(f"{BASE}/v3/depth").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "0"})
    )
    client = _client()
    with pytest.raises(RateLimitExceeded):
        await client.request("GET", "/v3/depth", params={"symbol": "BTCUSDT"})
    await client.close()


@respx.mock
async def test_server_error_retried_then_succeeds():
    route = respx.get(f"{BASE}/v3/exchangeInfo")
    route.side_effect = [
        httpx.Response(503),
        httpx.Response(200, json={"symbols": []}),
    ]
    client = _client()
    data = await client.request("GET", "/v3/exchangeInfo")
    assert data == {"symbols": []}
    assert route.call_count == 2
    await client.close()


@respx.mock
async def test_order_submission_never_retried():
    """Query-before-retry rule: ambiguous order failures must NOT auto-retry."""
    route = respx.post(f"{BASE}/v3/order").mock(side_effect=httpx.ConnectError("boom"))
    respx.get(f"{BASE}/v3/time").mock(
        return_value=httpx.Response(200, json={"serverTime": _now_ms()})
    )
    client = _client()
    await client.sync_time()
    with pytest.raises(ExchangeConnectionError):
        await client.request(
            "POST", "/v3/order", params={"symbol": "BTCUSDT"}, signed=True, is_order=True
        )
    assert route.call_count == 1  # exactly one attempt
    await client.close()


@respx.mock
async def test_api_error_carries_binance_code():
    respx.get(f"{BASE}/v3/depth").mock(
        return_value=httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."})
    )
    client = _client()
    with pytest.raises(ExchangeApiError) as excinfo:
        await client.request("GET", "/v3/depth", params={"symbol": "NOPE"})
    assert excinfo.value.code == -1121
    await client.close()
