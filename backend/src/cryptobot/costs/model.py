"""Transaction-cost model shared by backtest, paper and live paths.

Fractions are of notional (0.001 = 0.1%). The displayed price is never the
executed price: every fill pays half-spread + slippage (+ optional latency
drift), and every trade pays fees on both sides.

The cost gate (docs/risk-policy.md §6): a trade is acceptable only when its
conservative expected return exceeds full round-trip cost plus a safety
margin.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class CostModel:
    maker_fee: float = 0.001          # Binance spot default without BNB discount
    taker_fee: float = 0.001
    half_spread: float = 0.0003       # conservative for BTC/ETH majors
    slippage: float = 0.0005
    latency_drift: float = 0.0002     # adverse price move during order transit
    safety_margin: float = 0.001      # extra edge required beyond costs

    def buy_fill_price(self, reference: float) -> float:
        return reference * (1 + self.half_spread + self.slippage + self.latency_drift)

    def sell_fill_price(self, reference: float) -> float:
        return reference * (1 - self.half_spread - self.slippage - self.latency_drift)

    def fee(self, notional: float, taker: bool = True) -> float:
        return abs(notional) * (self.taker_fee if taker else self.maker_fee)

    @property
    def round_trip_fraction(self) -> float:
        """Total cost fraction of a buy+sell round trip (taker both sides)."""
        return 2 * (self.taker_fee + self.half_spread + self.slippage + self.latency_drift)

    def passes_cost_gate(self, conservative_expected_return: float) -> bool:
        """True only if expected return clears costs + safety margin."""
        return conservative_expected_return > self.round_trip_fraction + self.safety_margin

    def stressed(self, fee_mult: float = 1.0, slippage_mult: float = 1.0) -> CostModel:
        """Scaled copy for sensitivity analysis."""
        return replace(
            self,
            maker_fee=self.maker_fee * fee_mult,
            taker_fee=self.taker_fee * fee_mult,
            slippage=self.slippage * slippage_mult,
            half_spread=self.half_spread * slippage_mult,
        )
