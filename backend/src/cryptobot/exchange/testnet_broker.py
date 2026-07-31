"""Testnet broker — routes runtime orders to Binance Spot Testnet.

Same call shape as PaperBroker.execute_market so the runtime is broker-
agnostic. Applies symbol-filter validation and idempotent client order IDs;
confirms the final state from the exchange response (and query on ambiguity
via the adapter's no-blind-retry rule).

There is deliberately NO live equivalent of this class. Constructing an
execution path against api.binance.com requires the Phase-6-gated work that
does not exist in this codebase — asserted by test_no_live_path.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from cryptobot.core.logging import get_logger
from cryptobot.exchange.adapter import ExchangeAdapter
from cryptobot.exchange.errors import ExchangeError, FilterViolation
from cryptobot.exchange.filters import round_qty_down, validate_order
from cryptobot.exchange.models import (
    OrderRequest,
    OrderType,
    Side,
    SymbolRules,
)
from cryptobot.paper.broker import PaperExecution

logger = get_logger(__name__)

D = Decimal


class TestnetBroker:
    def __init__(self, adapter: ExchangeAdapter, rules_by_symbol: dict[str, SymbolRules]) -> None:
        self._adapter = adapter
        self._rules = rules_by_symbol

    async def execute_market(
        self,
        symbol: str,
        side: Side,
        qty: Decimal,
        reference_price: Decimal,
        base_asset: str,
        quote_asset: str,
        client_order_id: str | None = None,
    ) -> PaperExecution:
        rules = self._rules.get(symbol)
        if rules is None:
            raise ExchangeError(f"no exchange rules loaded for {symbol} — refusing to trade")

        qty = round_qty_down(qty, rules.step_size)
        request = OrderRequest(
            symbol=symbol, side=side, type=OrderType.MARKET, quantity=qty,
            client_order_id=client_order_id or f"cbt-{uuid.uuid4().hex[:24]}",
        )
        validate_order(request, rules, reference_price=reference_price)

        state = await self._adapter.place_order(request)
        if state.executed_qty <= 0:
            # Never assume; confirm the final state from the exchange.
            state = await self._adapter.query_order(symbol, request.client_order_id)
        if state.executed_qty <= 0:
            raise ExchangeError(
                f"testnet order {request.client_order_id} not filled "
                f"(status={state.status.value}) — position NOT opened"
            )
        fill_price = state.avg_fill_price or reference_price
        fee = sum((f.fee_amount for f in state.fills), D("0"))
        logger.info("testnet_fill", symbol=symbol, side=side.value,
                    qty=str(state.executed_qty), price=str(fill_price))
        return PaperExecution(
            order_id=state.exchange_order_id or request.client_order_id,
            client_order_id=request.client_order_id,
            symbol=symbol, side=side, qty=state.executed_qty,
            fill_price=fill_price, fee=fee,
            slippage_cost=abs(fill_price - reference_price) * state.executed_qty,
            reference_price=reference_price,
            executed_at=state.updated_at,
        )


__all__ = ["FilterViolation", "TestnetBroker"]
