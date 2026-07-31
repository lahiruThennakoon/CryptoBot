from decimal import Decimal

import pytest

from cryptobot.exchange.errors import FilterViolation
from cryptobot.exchange.filters import (
    max_affordable_qty,
    round_price,
    round_qty_down,
    validate_order,
)
from cryptobot.exchange.models import OrderRequest, OrderType, Side, SymbolRules

D = Decimal

RULES = SymbolRules(
    symbol="BTCUSDT",
    base_asset="BTC",
    quote_asset="USDT",
    status="TRADING",
    tick_size=D("0.01"),
    step_size=D("0.00001"),
    min_qty=D("0.00001"),
    max_qty=D("9000"),
    min_notional=D("5"),
)


def _limit(qty: str, price: str) -> OrderRequest:
    return OrderRequest(
        symbol="BTCUSDT", side=Side.BUY, type=OrderType.LIMIT,
        quantity=D(qty), price=D(price), client_order_id="test-0001-abcd",
    )


class TestRounding:
    def test_qty_rounds_down_never_up(self):
        assert round_qty_down(D("0.123456789"), D("0.00001")) == D("0.12345")

    def test_qty_exact_multiple_unchanged(self):
        assert round_qty_down(D("0.5"), D("0.00001")) == D("0.5")

    def test_price_rounds_to_tick(self):
        assert round_price(D("42000.123"), D("0.01")) == D("42000.12")

    def test_invalid_step_raises(self):
        with pytest.raises(FilterViolation):
            round_qty_down(D("1"), D("0"))


class TestValidateOrder:
    def test_valid_limit_order_passes(self):
        validate_order(_limit("0.001", "50000.00"), RULES)

    def test_below_min_notional_rejected(self):
        with pytest.raises(FilterViolation, match="min_notional"):
            validate_order(_limit("0.00001", "50000.00"), RULES)  # 0.50 USDT < 5

    def test_misaligned_qty_rejected(self):
        with pytest.raises(FilterViolation, match="step_size"):
            validate_order(_limit("0.000015", "50000.00"), RULES)

    def test_misaligned_price_rejected(self):
        with pytest.raises(FilterViolation, match="tick_size"):
            validate_order(_limit("0.001", "50000.005"), RULES)

    def test_non_trading_symbol_rejected(self):
        halted = RULES.model_copy(update={"status": "HALT"})
        with pytest.raises(FilterViolation, match="not TRADING"):
            validate_order(_limit("0.001", "50000.00"), halted)

    def test_market_order_requires_reference_price(self):
        req = OrderRequest(
            symbol="BTCUSDT", side=Side.BUY, type=OrderType.MARKET,
            quantity=D("0.001"), client_order_id="test-0002-abcd",
        )
        with pytest.raises(FilterViolation, match="reference price"):
            validate_order(req, RULES)
        validate_order(req, RULES, reference_price=D("50000"))

    def test_zero_qty_rejected(self):
        with pytest.raises(FilterViolation):
            validate_order(_limit("0", "50000.00"), RULES)


class TestMaxAffordable:
    def test_never_exceeds_balance(self):
        qty = max_affordable_qty(D("100"), D("50000"), RULES)
        assert qty * D("50000") <= D("100")

    def test_returns_zero_when_unaffordable(self):
        assert max_affordable_qty(D("1"), D("50000"), RULES) == 0  # < min_notional

    def test_zero_for_nonpositive_inputs(self):
        assert max_affordable_qty(D("0"), D("50000"), RULES) == 0
        assert max_affordable_qty(D("100"), D("0"), RULES) == 0
