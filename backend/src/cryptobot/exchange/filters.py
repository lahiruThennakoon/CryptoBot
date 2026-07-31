"""Local validation of Binance symbol filters.

Every order is validated here BEFORE submission. Quantities are always
rounded DOWN (never up) so we never exceed intended size or balance.
Property-based tests in tests/property/test_filter_rounding.py.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal

from cryptobot.exchange.errors import FilterViolation
from cryptobot.exchange.models import OrderRequest, OrderType, SymbolRules


def round_qty_down(qty: Decimal, step_size: Decimal) -> Decimal:
    """Round quantity down to the symbol's step size."""
    if step_size <= 0:
        raise FilterViolation(f"Invalid step_size {step_size}")
    steps = (qty / step_size).to_integral_value(rounding=ROUND_DOWN)
    return (steps * step_size).normalize() + Decimal(0)  # +0 normalizes -0


def round_price(price: Decimal, tick_size: Decimal) -> Decimal:
    """Round price to the nearest valid tick (banker's rounding)."""
    if tick_size <= 0:
        raise FilterViolation(f"Invalid tick_size {tick_size}")
    ticks = (price / tick_size).to_integral_value(rounding=ROUND_HALF_EVEN)
    return (ticks * tick_size).normalize() + Decimal(0)


def validate_order(
    request: OrderRequest, rules: SymbolRules, reference_price: Decimal | None = None
) -> None:
    """Raise FilterViolation unless the order satisfies all symbol filters.

    For MARKET orders a reference_price (e.g. best bid/ask) is required to
    check MIN_NOTIONAL conservatively.
    """
    if not rules.is_trading:
        raise FilterViolation(f"{rules.symbol} status is {rules.status}, not TRADING")

    qty = request.quantity
    if qty <= 0:
        raise FilterViolation("Quantity must be positive")
    if qty < rules.min_qty:
        raise FilterViolation(f"Quantity {qty} < min_qty {rules.min_qty}")
    if qty > rules.max_qty:
        raise FilterViolation(f"Quantity {qty} > max_qty {rules.max_qty}")
    if round_qty_down(qty, rules.step_size) != qty.normalize() + Decimal(0):
        raise FilterViolation(f"Quantity {qty} not aligned to step_size {rules.step_size}")

    if request.type is OrderType.LIMIT:
        if request.price is None:
            raise FilterViolation("LIMIT order requires a price")
        if request.price <= 0:
            raise FilterViolation("Price must be positive")
        if round_price(request.price, rules.tick_size) != request.price.normalize() + Decimal(0):
            raise FilterViolation(
                f"Price {request.price} not aligned to tick_size {rules.tick_size}"
            )
        notional_price = request.price
    else:
        if reference_price is None or reference_price <= 0:
            raise FilterViolation("MARKET order requires a positive reference price")
        notional_price = reference_price

    notional = qty * notional_price
    if notional < rules.min_notional:
        raise FilterViolation(
            f"Notional {notional} < min_notional {rules.min_notional} for {rules.symbol}"
        )


def max_affordable_qty(
    available_quote: Decimal, price: Decimal, rules: SymbolRules
) -> Decimal:
    """Largest filter-valid quantity purchasable with available_quote at price.

    Returns 0 if nothing valid is affordable. Never exceeds the balance.
    """
    if price <= 0 or available_quote <= 0:
        return Decimal(0)
    qty = round_qty_down(available_quote / price, rules.step_size)
    # Decimal division rounds at context precision and may round the quotient
    # UP by a hair before flooring; step down until notional fits the balance.
    while qty > 0 and qty * price > available_quote:
        qty -= rules.step_size
    if qty < rules.min_qty or qty * price < rules.min_notional:
        return Decimal(0)
    return min(qty, rules.max_qty)
