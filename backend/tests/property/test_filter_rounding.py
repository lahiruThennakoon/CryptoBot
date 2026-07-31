"""Property-based tests for order-sizing and filter math (Hypothesis)."""

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from cryptobot.exchange.filters import max_affordable_qty, round_price, round_qty_down
from cryptobot.exchange.models import SymbolRules

D = Decimal

qty_st = st.decimals(min_value="0", max_value="1000000", places=10, allow_nan=False, allow_infinity=False)
price_st = st.decimals(min_value="0.00000001", max_value="10000000", places=8, allow_nan=False, allow_infinity=False)
step_st = st.sampled_from([D("0.1"), D("0.01"), D("0.001"), D("0.00001"), D("0.00000001"), D("1")])
tick_st = st.sampled_from([D("0.01"), D("0.001"), D("0.0001"), D("0.00000001"), D("1")])
balance_st = st.decimals(min_value="0", max_value="100000000", places=8, allow_nan=False, allow_infinity=False)


@given(qty=qty_st, step=step_st)
@settings(max_examples=300)
def test_round_qty_never_rounds_up(qty: Decimal, step: Decimal) -> None:
    rounded = round_qty_down(qty, step)
    assert rounded <= qty
    assert rounded >= 0


@given(qty=qty_st, step=step_st)
@settings(max_examples=300)
def test_round_qty_is_step_aligned_and_idempotent(qty: Decimal, step: Decimal) -> None:
    rounded = round_qty_down(qty, step)
    assert (rounded / step) % 1 == 0          # exact multiple of step
    assert round_qty_down(rounded, step) == rounded  # idempotent


@given(qty=qty_st, step=step_st)
@settings(max_examples=300)
def test_round_qty_loses_less_than_one_step(qty: Decimal, step: Decimal) -> None:
    rounded = round_qty_down(qty, step)
    assert qty - rounded < step


@given(price=price_st, tick=tick_st)
@settings(max_examples=300)
def test_round_price_is_tick_aligned_within_half_tick(price: Decimal, tick: Decimal) -> None:
    rounded = round_price(price, tick)
    assert (rounded / tick) % 1 == 0
    assert abs(rounded - price) <= tick / 2


@given(balance=balance_st, price=price_st, step=step_st)
@settings(max_examples=300)
def test_max_affordable_never_exceeds_balance(
    balance: Decimal, price: Decimal, step: Decimal
) -> None:
    rules = SymbolRules(
        symbol="TESTUSDT", base_asset="TEST", quote_asset="USDT", status="TRADING",
        tick_size=D("0.01"), step_size=step, min_qty=step, max_qty=D("1000000000"),
        min_notional=D("5"),
    )
    qty = max_affordable_qty(balance, price, rules)
    assert qty >= 0
    assert qty * price <= balance                      # never overspend
    if qty > 0:
        assert qty >= rules.min_qty                    # filter-valid
        assert qty * price >= rules.min_notional
        assert (qty / step) % 1 == 0
