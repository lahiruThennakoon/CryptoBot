"""Real Binance Spot Testnet integration tests.

Opt-in: `pytest -m testnet`. Requires BINANCE_TESTNET_API_KEY/SECRET in env.
Excluded from CI and the default run (see pyproject addopts).
"""

import os
import uuid
from decimal import Decimal

import pytest

from cryptobot.config.settings import Settings

pytestmark = [
    pytest.mark.testnet,
    pytest.mark.skipif(
        not os.environ.get("BINANCE_TESTNET_API_KEY"),
        reason="BINANCE_TESTNET_API_KEY not set",
    ),
]


@pytest.fixture
async def adapter():
    from cryptobot.exchange.binance.adapter import BinanceSpotAdapter
    from cryptobot.exchange.binance.client import BinanceRestClient

    settings = Settings(CRYPTOBOT_MODE="testnet")
    client = BinanceRestClient(
        base_url=settings.rest_base_url,
        api_key=settings.api_key,
        api_secret=settings.api_secret,
    )
    adapter = BinanceSpotAdapter(client, settings.ws_base_url)
    await client.sync_time()
    yield adapter
    await adapter.close()


async def test_connectivity_and_permissions(adapter):
    await adapter.verify_connectivity()
    account = await adapter.get_account()
    assert account.can_trade
    # The testnet key must never be able to withdraw:
    assert not account.can_withdraw


async def test_exchange_rules_contain_configured_pairs(adapter):
    rules = await adapter.get_exchange_rules()
    for symbol in ("BTCUSDT", "ETHUSDT"):
        assert symbol in rules.symbols
        assert rules.symbols[symbol].tick_size > 0
        assert rules.symbols[symbol].step_size > 0


async def test_klines_are_chronological(adapter):
    candles = await adapter.get_klines("BTCUSDT", "1m", limit=50)
    assert len(candles) > 0
    times = [c.open_time for c in candles]
    assert times == sorted(times)


async def test_order_lifecycle_place_query_cancel(adapter):
    """Place a deliberately unfillable limit buy, confirm state, cancel it."""
    rules = (await adapter.get_exchange_rules()).symbols["BTCUSDT"]
    book = await adapter.get_order_book("BTCUSDT", limit=5)
    assert book.best_bid is not None

    from cryptobot.exchange.filters import round_price, round_qty_down, validate_order
    from cryptobot.exchange.models import OrderRequest, OrderType, Side, TimeInForce

    price = round_price(book.best_bid.price * Decimal("0.5"), rules.tick_size)  # far below market
    qty = round_qty_down(
        max(rules.min_notional / price * Decimal("1.05"), rules.min_qty), rules.step_size
    )
    request = OrderRequest(
        symbol="BTCUSDT", side=Side.BUY, type=OrderType.LIMIT, quantity=qty,
        price=price, time_in_force=TimeInForce.GTC,
        client_order_id=f"cbt-{uuid.uuid4().hex[:20]}",
    )
    validate_order(request, rules)

    placed = await adapter.place_order(request)
    assert placed.client_order_id == request.client_order_id

    queried = await adapter.query_order("BTCUSDT", request.client_order_id)
    assert queried.status.value in ("NEW", "PARTIALLY_FILLED")

    canceled = await adapter.cancel_order("BTCUSDT", request.client_order_id)
    assert canceled.status.value == "CANCELED"


async def test_duplicate_client_order_id_rejected(adapter):
    """Idempotency: same clientOrderId cannot create a second live order."""
    rules = (await adapter.get_exchange_rules()).symbols["BTCUSDT"]
    book = await adapter.get_order_book("BTCUSDT", limit=5)
    from cryptobot.exchange.errors import ExchangeApiError
    from cryptobot.exchange.filters import round_price, round_qty_down
    from cryptobot.exchange.models import OrderRequest, OrderType, Side, TimeInForce

    price = round_price(book.best_bid.price * Decimal("0.5"), rules.tick_size)
    qty = round_qty_down(
        max(rules.min_notional / price * Decimal("1.05"), rules.min_qty), rules.step_size
    )
    request = OrderRequest(
        symbol="BTCUSDT", side=Side.BUY, type=OrderType.LIMIT, quantity=qty,
        price=price, time_in_force=TimeInForce.GTC,
        client_order_id=f"cbt-{uuid.uuid4().hex[:20]}",
    )
    await adapter.place_order(request)
    try:
        with pytest.raises(ExchangeApiError):
            await adapter.place_order(request)  # duplicate must be rejected
    finally:
        await adapter.cancel_order("BTCUSDT", request.client_order_id)
