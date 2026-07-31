"""Paper broker — cost-aware simulated execution against live market prices.

Same cost model as the backtester (fees + half-spread + slippage + latency
drift), so paper results remain comparable to backtest results. Market-order
execution policy in Phase 4; limit-order simulation arrives with the
execution-policy work. Every fill mutates the PaperAccount atomically.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from cryptobot.costs.model import CostModel
from cryptobot.exchange.models import Side
from cryptobot.paper.account import PaperAccount, PaperFill

D = Decimal


@dataclass(frozen=True)
class PaperExecution:
    order_id: str
    client_order_id: str
    symbol: str
    side: Side
    qty: Decimal
    fill_price: Decimal
    fee: Decimal
    slippage_cost: Decimal      # |fill − reference| × qty
    reference_price: Decimal
    executed_at: datetime


class PaperBroker:
    def __init__(self, account: PaperAccount, costs: CostModel | None = None) -> None:
        self.account = account
        self._costs = costs or CostModel()

    def execute_maker_limit(
        self,
        symbol: str,
        side: Side,
        qty: Decimal,
        limit_price: Decimal,
        base_asset: str,
        quote_asset: str,
        client_order_id: str | None = None,
    ) -> PaperExecution:
        """Simulate a MAKER fill at the resting limit price.

        Only called once the caller has confirmed the market actually traded
        through the limit (see the runtime's maker-order lifecycle), so no
        fill is invented. Maker fills pay the maker fee, cross no spread and
        take no entry slippage — that is the entire point of the policy.
        """
        if qty <= 0 or limit_price <= 0:
            raise ValueError("qty and limit_price must be positive")
        fee = (qty * limit_price * D(str(self._costs.maker_fee))).quantize(D("0.00000001"))
        self.account.apply_fill(
            PaperFill(symbol=symbol, side=side, price=limit_price, qty=qty,
                      fee_amount=fee, fee_asset=quote_asset),
            base_asset=base_asset, quote_asset=quote_asset,
        )
        return PaperExecution(
            order_id=uuid.uuid4().hex,
            client_order_id=client_order_id or f"paper-mk-{uuid.uuid4().hex[:20]}",
            symbol=symbol, side=side, qty=qty, fill_price=limit_price, fee=fee,
            slippage_cost=D("0"), reference_price=limit_price,
            executed_at=datetime.now(UTC),
        )

    def execute_market(
        self,
        symbol: str,
        side: Side,
        qty: Decimal,
        reference_price: Decimal,
        base_asset: str,
        quote_asset: str,
        client_order_id: str | None = None,
    ) -> PaperExecution:
        """Simulate an immediate market fill at reference ± costs.

        Raises InsufficientBalanceError before mutating anything if the
        account cannot cover the fill (never oversell / overspend).
        """
        if qty <= 0 or reference_price <= 0:
            raise ValueError("qty and reference_price must be positive")

        ref = float(reference_price)
        fill_f = (
            self._costs.buy_fill_price(ref) if side is Side.BUY else self._costs.sell_fill_price(ref)
        )
        fill_price = D(str(fill_f)).quantize(D("0.00000001"))
        fee = (qty * fill_price * D(str(self._costs.taker_fee))).quantize(D("0.00000001"))

        self.account.apply_fill(
            PaperFill(symbol=symbol, side=side, price=fill_price, qty=qty,
                      fee_amount=fee, fee_asset=quote_asset),
            base_asset=base_asset,
            quote_asset=quote_asset,
        )
        return PaperExecution(
            order_id=uuid.uuid4().hex,
            client_order_id=client_order_id or f"paper-{uuid.uuid4().hex[:24]}",
            symbol=symbol,
            side=side,
            qty=qty,
            fill_price=fill_price,
            fee=fee,
            slippage_cost=(abs(fill_price - reference_price) * qty).quantize(D("0.00000001")),
            reference_price=reference_price,
            executed_at=datetime.now(UTC),
        )
