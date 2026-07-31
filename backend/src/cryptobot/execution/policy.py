"""Execution policy: market (taker) vs resting limit (maker).

Maker orders are the one profit lever fully under our control: they pay the
maker fee instead of the taker fee, don't cross the spread, and suffer no
entry slippage. The cost is honest and must be modelled: a resting order may
never fill, which means missed trades (opportunity cost), and adverse
selection — resting bids fill more often precisely when price is falling.

Exits are deliberately allowed to use market orders even under a maker
policy: when a stop is hit, certainty of exit outranks saving a fee.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from cryptobot.costs.model import CostModel


class OrderStyle(str, Enum):
    MARKET = "market"          # taker: certain fill, pays spread + slippage
    MAKER_LIMIT = "maker_limit"  # maker: cheaper, may not fill


@dataclass(frozen=True)
class ExecutionPolicy:
    entry_style: OrderStyle = OrderStyle.MARKET
    exit_style: OrderStyle = OrderStyle.MARKET      # protective exits stay market
    limit_offset_bps: float = 2.0                   # rest this far below best bid
    ttl_bars: int = 3                               # cancel if unfilled after N bars
    bnb_discount: float = 0.0                       # 0.25 if paying fees in BNB

    @property
    def uses_maker_entries(self) -> bool:
        return self.entry_style is OrderStyle.MAKER_LIMIT


def effective_costs(costs: CostModel, policy: ExecutionPolicy) -> CostModel:
    """Cost model reflecting the policy, for the cost gate and backtests.

    Maker entries remove the spread/slippage/latency drag on the entry leg
    and pay the maker fee; the exit leg is unchanged when exits are market.
    Fee discounts (BNB) apply to both legs.
    """
    discount = 1.0 - policy.bnb_discount
    adjusted = replace(
        costs,
        maker_fee=costs.maker_fee * discount,
        taker_fee=costs.taker_fee * discount,
    )
    if not policy.uses_maker_entries:
        return adjusted
    # entry leg costs collapse to the maker fee: halve the two-sided
    # spread/slippage/latency components (exit leg still pays its share).
    return replace(
        adjusted,
        half_spread=adjusted.half_spread / 2,
        slippage=adjusted.slippage / 2,
        latency_drift=adjusted.latency_drift / 2,
    )


def limit_price_for_entry(reference_price: float, policy: ExecutionPolicy) -> float:
    """Resting bid price for a maker entry (below the reference)."""
    return reference_price * (1 - policy.limit_offset_bps / 10_000)


def savings_estimate(costs: CostModel, policy: ExecutionPolicy,
                     notional: float, trades_per_month: float) -> dict[str, float]:
    """What switching to maker entries + fee discount is worth, in money."""
    taker_rt = costs.round_trip_fraction
    maker_rt = effective_costs(costs, policy).round_trip_fraction
    per_trade = notional * max(0.0, taker_rt - maker_rt)
    return {
        "per_trade_usd": round(per_trade, 4),
        "per_month_usd": round(per_trade * trades_per_month, 2),
        "taker_round_trip_pct": round(taker_rt * 100, 4),
        "policy_round_trip_pct": round(maker_rt * 100, 4),
    }
