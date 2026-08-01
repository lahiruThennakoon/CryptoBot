"""Live cost discovery: real fees from Binance, real spread, depth-based slippage.

Why this exists: the cost gate decides every trade, so assumed costs mean
wrong decisions. Everything here is fetched from the exchange and tagged with
its provenance (LIVE vs ASSUMED) and timestamp, so a cost figure can never
silently pretend to be authoritative.

Endpoints (verified against official binance-spot-api-docs):
  GET /api/v3/account            → commissionRates {maker, taker, buyer, seller}
  GET /api/v3/account/commission → per-symbol standardCommission + taxCommission
                                   + specialCommission + discount{...}  (signed)
  GET /api/v3/depth              → order book for slippage estimation

Commission maths follows the official commission FAQ: the rate applied is the
sum of the relevant components (e.g. taker + buyer for a BUY), the BNB
discount applies ONLY to standardCommission, and tax/special commissions are
never discounted.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from cryptobot.core.logging import get_logger
from cryptobot.costs.model import CostModel
from cryptobot.exchange.models import OrderBook

logger = get_logger(__name__)

# Conservative fallbacks used only when the exchange cannot be asked.
# Deliberately pessimistic: over-estimating costs rejects marginal trades,
# which is the safe direction to be wrong in.
ASSUMED_TAKER = 0.001
ASSUMED_MAKER = 0.001
ASSUMED_SPREAD = 0.0006
ASSUMED_SLIPPAGE = 0.0005


class Provenance(str, Enum):
    LIVE = "live"          # fetched from the exchange
    ASSUMED = "assumed"    # conservative fallback — flag it loudly
    STALE = "stale"        # fetched, but older than the refresh window


@dataclass
class FeeSchedule:
    symbol: str
    maker_rate: float
    taker_rate: float
    discount_asset: str = ""
    discount_applied: float = 0.0
    provenance: Provenance = Provenance.ASSUMED
    fetched_at: float = 0.0
    detail: str = ""

    def age_s(self) -> float:
        return time.time() - self.fetched_at if self.fetched_at else float("inf")


def parse_commission_response(raw: dict[str, Any], symbol: str) -> FeeSchedule:
    """Parse GET /api/v3/account/commission into effective maker/taker rates.

    Effective rate = standard (discounted if BNB discount active) + tax +
    special. Buyer/seller components are added because they apply per side.
    """
    def rate(block: str, key: str) -> float:
        return float(raw.get(block, {}).get(key, 0) or 0)

    discount_info = raw.get("discount", {}) or {}
    discount = 0.0
    if discount_info.get("enabledForAccount") and discount_info.get("enabledForSymbol"):
        discount = float(discount_info.get("discount", 0) or 0)

    # standard is discountable; tax and special are not
    std_maker = rate("standardCommission", "maker") + rate("standardCommission", "buyer")
    std_taker = rate("standardCommission", "taker") + rate("standardCommission", "buyer")
    non_disc_maker = (rate("taxCommission", "maker") + rate("taxCommission", "buyer")
                      + rate("specialCommission", "maker") + rate("specialCommission", "buyer"))
    non_disc_taker = (rate("taxCommission", "taker") + rate("taxCommission", "buyer")
                      + rate("specialCommission", "taker") + rate("specialCommission", "buyer"))

    maker = std_maker * (1 - discount) + non_disc_maker
    taker = std_taker * (1 - discount) + non_disc_taker
    return FeeSchedule(
        symbol=symbol, maker_rate=maker, taker_rate=taker,
        discount_asset=str(discount_info.get("discountAsset", "") or ""),
        discount_applied=discount, provenance=Provenance.LIVE, fetched_at=time.time(),
        detail=("per-symbol commission from /api/v3/account/commission"
                + (f"; {discount:.0%} {discount_info.get('discountAsset')} discount active"
                   if discount else "; no fee discount active")),
    )


def parse_account_commission_rates(raw: dict[str, Any], symbol: str) -> FeeSchedule:
    """Fallback: account-wide commissionRates from GET /api/v3/account."""
    rates = raw.get("commissionRates", {}) or {}
    maker = float(rates.get("maker", ASSUMED_MAKER) or ASSUMED_MAKER)
    taker = float(rates.get("taker", ASSUMED_TAKER) or ASSUMED_TAKER)
    buyer = float(rates.get("buyer", 0) or 0)
    return FeeSchedule(
        symbol=symbol, maker_rate=maker + buyer, taker_rate=taker + buyer,
        provenance=Provenance.LIVE, fetched_at=time.time(),
        detail="account-wide commissionRates from /api/v3/account",
    )


class FeeService:
    """Fetches and caches real commission rates per symbol.

    Falls back conservatively and never blocks trading on a fee-lookup
    failure — but the resulting schedule is tagged ASSUMED so the UI, the
    assistant and the decision record all say so.
    """

    def __init__(self, client: Any, refresh_after_s: float = 3600.0) -> None:
        self._client = client
        self._refresh_after_s = refresh_after_s
        self._cache: dict[str, FeeSchedule] = {}

    def cached(self, symbol: str) -> FeeSchedule | None:
        schedule = self._cache.get(symbol)
        if schedule and schedule.age_s() > self._refresh_after_s:
            return replace(schedule, provenance=Provenance.STALE)
        return schedule

    async def get(self, symbol: str, force: bool = False) -> FeeSchedule:
        cached = self._cache.get(symbol)
        if cached and not force and cached.age_s() <= self._refresh_after_s:
            return cached
        # 1. per-symbol commission (most accurate: includes discounts + tax)
        try:
            raw = await self._client.request(
                "GET", "/v3/account/commission", params={"symbol": symbol},
                signed=True, weight=20,
            )
            schedule = parse_commission_response(raw, symbol)
            self._cache[symbol] = schedule
            logger.info("fees_live", symbol=symbol, maker=schedule.maker_rate,
                        taker=schedule.taker_rate, discount=schedule.discount_applied)
            return schedule
        except Exception as exc:  # noqa: BLE001 — fall through to broader source
            logger.warning("fee_lookup_per_symbol_failed", symbol=symbol,
                           error=type(exc).__name__)
        # 2. account-wide rates
        try:
            raw = await self._client.request("GET", "/v3/account", signed=True, weight=20)
            schedule = parse_account_commission_rates(raw, symbol)
            self._cache[symbol] = schedule
            return schedule
        except Exception as exc:  # noqa: BLE001
            logger.warning("fee_lookup_account_failed", symbol=symbol,
                           error=type(exc).__name__)
        # 3. conservative assumption, clearly labelled
        return FeeSchedule(
            symbol=symbol, maker_rate=ASSUMED_MAKER, taker_rate=ASSUMED_TAKER,
            provenance=Provenance.ASSUMED, fetched_at=time.time(),
            detail="exchange fee lookup unavailable — using conservative 0.10% assumption",
        )


# ── depth-based slippage estimation ───────────────────────────────────
@dataclass
class SlippageEstimate:
    fraction: float                 # expected slippage vs best price
    filled_notional: float
    depth_sufficient: bool
    levels_consumed: int
    provenance: Provenance
    detail: str = ""


def estimate_slippage(book: OrderBook, notional: float, side: str = "buy") -> SlippageEstimate:
    """Walk the real order book to estimate the fill price for `notional`.

    This is the difference between a hopeful assumption and arithmetic: if the
    top of book cannot absorb the order, the estimate rises accordingly.
    """
    levels = book.asks if side == "buy" else book.bids
    if not levels or notional <= 0:
        return SlippageEstimate(ASSUMED_SLIPPAGE, 0.0, False, 0,
                                Provenance.ASSUMED,
                                "no order-book data — conservative assumption used")
    best = float(levels[0].price)
    remaining = notional
    spent = 0.0
    quantity = 0.0
    consumed = 0
    for level in levels:
        price = float(level.price)
        available_notional = price * float(level.qty)
        take = min(remaining, available_notional)
        if take <= 0:
            break
        quantity += take / price
        spent += take
        remaining -= take
        consumed += 1
        if remaining <= 0:
            break
    if quantity <= 0:
        return SlippageEstimate(ASSUMED_SLIPPAGE, 0.0, False, 0, Provenance.ASSUMED,
                                "order book too thin to model — assumption used")
    vwap = spent / quantity
    fraction = abs(vwap - best) / best if best > 0 else ASSUMED_SLIPPAGE
    sufficient = remaining <= 0
    unfilled_ratio = 0.0
    if not sufficient:
        # The book cannot absorb the order. Penalise in proportion to how much
        # could NOT be filled — an order that fills 1% is far worse than one
        # that fills 95%. Callers must ALSO treat depth_sufficient=False as a
        # liquidity block: a price for size that doesn't exist is fiction.
        unfilled_ratio = max(0.0, min(1.0, remaining / notional))
        fraction = max(fraction, ASSUMED_SLIPPAGE) * (1 + 10 * unfilled_ratio)
    return SlippageEstimate(
        fraction=fraction, filled_notional=spent, depth_sufficient=sufficient,
        levels_consumed=consumed, provenance=Provenance.LIVE,
        detail=(f"walked {consumed} book level(s); "
                + ("full size absorbed" if sufficient
                   else f"BOOK EXHAUSTED — only {(1-unfilled_ratio)*100:.0f}% of the "
                        "order could fill; treat as insufficient liquidity")),
    )


# ── composing a live cost model ───────────────────────────────────────
@dataclass
class LiveCostBasis:
    symbol: str
    model: CostModel
    fee_provenance: Provenance
    spread_provenance: Provenance
    slippage_provenance: Provenance
    notes: list[str] = field(default_factory=list)
    book: OrderBook | None = None

    @property
    def all_live(self) -> bool:
        return all(p is Provenance.LIVE for p in
                   (self.fee_provenance, self.spread_provenance, self.slippage_provenance))

    def summary(self) -> str:
        kind = "measured from the exchange" if self.all_live else (
            "partly assumed — see notes")
        return (f"{self.symbol}: round trip {self.model.round_trip_fraction*100:.3f}% "
                f"({kind})")


def build_live_cost_model(
    symbol: str,
    fees: FeeSchedule,
    book: OrderBook | None,
    intended_notional: float,
    base: CostModel | None = None,
    safety_margin: float | None = None,
) -> LiveCostBasis:
    """Compose a CostModel from live fees, live spread and depth-derived slippage."""
    base = base or CostModel()
    notes: list[str] = [fees.detail] if fees.detail else []

    spread_fraction = None
    spread_provenance = Provenance.ASSUMED
    if book is not None and book.best_bid and book.best_ask:
        mid = book.mid
        if mid and mid > 0:
            spread_fraction = float((book.best_ask.price - book.best_bid.price) / mid)
            spread_provenance = Provenance.LIVE
    if spread_fraction is None:
        spread_fraction = ASSUMED_SPREAD
        notes.append("live spread unavailable — conservative assumption used")

    if book is not None:
        slip = estimate_slippage(book, intended_notional, side="buy")
    else:
        slip = SlippageEstimate(ASSUMED_SLIPPAGE, 0.0, False, 0, Provenance.ASSUMED,
                                "no order book — conservative slippage assumption")
    if slip.detail:
        notes.append(slip.detail)

    model = replace(
        base,
        maker_fee=fees.maker_rate,
        taker_fee=fees.taker_rate,
        half_spread=spread_fraction / 2,
        slippage=slip.fraction,
        safety_margin=base.safety_margin if safety_margin is None else safety_margin,
    )
    return LiveCostBasis(
        symbol=symbol, model=model,
        fee_provenance=fees.provenance,
        spread_provenance=spread_provenance,
        slippage_provenance=slip.provenance,
        notes=notes,
        book=book,
    )
