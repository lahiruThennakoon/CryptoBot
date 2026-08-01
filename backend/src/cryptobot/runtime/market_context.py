"""Build DecisionScorer MarketContext from live exchange data."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from cryptobot.costs.live import estimate_slippage
from cryptobot.decision.scoring import MarketContext
from cryptobot.exchange.models import OrderBook
from cryptobot.strategies.base import BarLike


def book_imbalance(book: OrderBook, levels: int = 10) -> float:
    bid_vol = sum(float(level.qty) for level in book.bids[:levels])
    ask_vol = sum(float(level.qty) for level in book.asks[:levels])
    total = bid_vol + ask_vol
    if total <= 0:
        return 0.0
    return (bid_vol - ask_vol) / total


async def build_market_context(
    symbol: str,
    bars: Sequence[BarLike],
    *,
    has_open_position: bool,
    data_fresh: bool,
    intended_notional: float,
    live_costs: Callable[[str, float], Awaitable[Any]] | None,
    ml_predictor: Callable[[Sequence[BarLike]], float | None] | None = None,
    btc_bars: Sequence[BarLike] | None = None,
) -> MarketContext:
    """Compose scorer context from live book data and optional ML prediction."""
    spread_fraction: float | None = None
    liquidity_ok = True
    imbalance: float | None = None
    book: OrderBook | None = None

    if live_costs is not None:
        try:
            basis = await live_costs(symbol, intended_notional)
            book = getattr(basis, "book", None)
            model = basis.model
            spread_fraction = model.half_spread * 2
            if book is not None:
                slip = estimate_slippage(book, intended_notional, side="buy")
                liquidity_ok = slip.depth_sufficient
                imbalance = book_imbalance(book)
        except Exception:  # noqa: BLE001 — degrade gracefully
            pass

    ml_probability_up: float | None = None
    if ml_predictor is not None:
        try:
            btc_closes = (
                [float(b.close) for b in btc_bars]  # type: ignore[arg-type]
                if btc_bars else None
            )
            ml_probability_up = ml_predictor(bars, btc_closes)
        except Exception:  # noqa: BLE001
            ml_probability_up = None

    return MarketContext(
        spread_fraction=spread_fraction,
        book_imbalance=imbalance,
        liquidity_ok=liquidity_ok,
        data_fresh=data_fresh,
        ml_probability_up=ml_probability_up,
        has_open_position=has_open_position,
    )
