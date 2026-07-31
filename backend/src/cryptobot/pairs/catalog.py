"""Trading-pair catalog: discovery, live stats, warnings, selectability.

Tradability comes from the ACTIVE venue's exchangeInfo (testnet in paper/
testnet modes — a pair must be tradable where orders would go). Market
statistics come from Binance live public REST (real prices/volumes; public
data, no API key). The pure evaluation logic is separated from I/O so it is
fully testable offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

D = Decimal

SUPPORTED_QUOTES = ("USDT", "FDUSD", "USDC")

# Warning thresholds (engineering defaults; conservative, configurable later)
LOW_LIQUIDITY_QUOTE_VOLUME_24H = D("50000000")   # < $50M/24h → low liquidity
WIDE_SPREAD_FRACTION = D("0.001")                # > 0.10% → wide spread
HIGH_VOLATILITY_24H = D("0.10")                  # 24h range > 10% of price


@dataclass
class PairStats:
    symbol: str
    last_price: Decimal = D("0")
    price_change_pct_24h: Decimal = D("0")
    quote_volume_24h: Decimal = D("0")
    high_24h: Decimal = D("0")
    low_24h: Decimal = D("0")
    best_bid: Decimal = D("0")
    best_ask: Decimal = D("0")

    @property
    def spread_fraction(self) -> Decimal:
        if self.best_bid > 0 and self.best_ask > 0:
            mid = (self.best_bid + self.best_ask) / 2
            return (self.best_ask - self.best_bid) / mid if mid > 0 else D("0")
        return D("0")

    @property
    def volatility_24h(self) -> Decimal:
        if self.last_price > 0 and self.high_24h > 0:
            return (self.high_24h - self.low_24h) / self.last_price
        return D("0")


@dataclass
class PairListing:
    symbol: str
    base_asset: str
    quote_asset: str
    status: str
    stats: PairStats
    selectable: bool = True
    not_selectable_reason: str = ""
    warnings: list[str] = field(default_factory=list)
    enabled: bool = False


def evaluate_pair(
    symbol: str,
    base_asset: str,
    quote_asset: str,
    status: str,
    stats: PairStats,
    is_spot_allowed: bool = True,
) -> PairListing:
    """Pure: selectability rules + pre-enable warnings."""
    listing = PairListing(symbol=symbol, base_asset=base_asset,
                          quote_asset=quote_asset, status=status, stats=stats)

    if status != "TRADING":
        listing.selectable = False
        listing.not_selectable_reason = f"pair status is {status}, not TRADING"
    elif not is_spot_allowed:
        listing.selectable = False
        listing.not_selectable_reason = "spot trading not permitted for this pair"
    elif quote_asset not in SUPPORTED_QUOTES:
        listing.selectable = False
        listing.not_selectable_reason = (
            f"quote asset {quote_asset} not supported (allowed: {', '.join(SUPPORTED_QUOTES)})"
        )

    if listing.selectable:
        if stats.quote_volume_24h and stats.quote_volume_24h < LOW_LIQUIDITY_QUOTE_VOLUME_24H:
            listing.warnings.append(
                f"Low liquidity: 24h volume ${float(stats.quote_volume_24h)/1e6:.0f}M — "
                "orders may move the price against you (higher slippage)."
            )
        if stats.spread_fraction > WIDE_SPREAD_FRACTION:
            listing.warnings.append(
                f"Wide spread: {float(stats.spread_fraction)*100:.2f}% — every round trip "
                "starts this far behind before fees."
            )
        if stats.volatility_24h > HIGH_VOLATILITY_24H:
            listing.warnings.append(
                f"High volatility: 24h range {float(stats.volatility_24h)*100:.0f}% of price — "
                "stops trigger more often and losses can be fast."
            )
    return listing


def parse_24h_ticker(raw: dict[str, Any]) -> PairStats:
    """Parse one row of GET /api/v3/ticker/24hr (official field names)."""
    return PairStats(
        symbol=str(raw["symbol"]),
        last_price=D(str(raw.get("lastPrice", "0"))),
        price_change_pct_24h=D(str(raw.get("priceChangePercent", "0"))),
        quote_volume_24h=D(str(raw.get("quoteVolume", "0"))),
        high_24h=D(str(raw.get("highPrice", "0"))),
        low_24h=D(str(raw.get("lowPrice", "0"))),
        best_bid=D(str(raw.get("bidPrice", "0"))),
        best_ask=D(str(raw.get("askPrice", "0"))),
    )
