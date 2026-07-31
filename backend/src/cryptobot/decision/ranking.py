"""Opportunity ranking across pairs (pure).

Rank qualifying BUY decisions by expected net return per unit of risk, then
drop candidates highly correlated with a stronger one — two positions that
move together are one position with double the risk.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from cryptobot.decision.scoring import Action, DecisionRecord

DEFAULT_CORRELATION_LIMIT = 0.8


@dataclass(frozen=True)
class RankedOpportunity:
    record: DecisionRecord
    risk_adjusted_return: float
    rank: int
    selected: bool
    excluded_reason: str = ""


def _risk_adjusted(record: DecisionRecord) -> float | None:
    if (
        record.expected_net_return is None
        or record.entry_estimate is None
        or record.stop_price is None
        or record.entry_estimate <= 0
    ):
        return None
    stop_distance = (record.entry_estimate - record.stop_price) / record.entry_estimate
    if stop_distance <= 0:
        return None
    return record.expected_net_return / stop_distance


def returns_correlation(a: Sequence[float], b: Sequence[float]) -> float:
    """Pearson correlation of two aligned return series."""
    n = min(len(a), len(b))
    if n < 10:
        return 0.0
    xs, ys = list(a[-n:]), list(b[-n:])
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return 0.0
    return cov / math.sqrt(vx * vy)


def rank_opportunities(
    decisions: list[DecisionRecord],
    returns_by_symbol: dict[str, Sequence[float]] | None = None,
    max_selected: int = 3,
    correlation_limit: float = DEFAULT_CORRELATION_LIMIT,
) -> list[RankedOpportunity]:
    """Deterministic: sorted by risk-adjusted return, ties by symbol."""
    candidates: list[tuple[DecisionRecord, float]] = []
    for record in decisions:
        if record.action is not Action.BUY:
            continue
        rar = _risk_adjusted(record)
        if rar is not None and rar > 0:
            candidates.append((record, rar))
    candidates.sort(key=lambda c: (-c[1], c[0].symbol))

    out: list[RankedOpportunity] = []
    selected_symbols: list[str] = []
    for rank, (record, rar) in enumerate(candidates, start=1):
        excluded = ""
        if len(selected_symbols) >= max_selected:
            excluded = f"only the top {max_selected} opportunities are taken per cycle"
        elif returns_by_symbol is not None:
            series = returns_by_symbol.get(record.symbol, [])
            for chosen in selected_symbols:
                corr = returns_correlation(series, returns_by_symbol.get(chosen, []))
                if corr > correlation_limit:
                    excluded = (
                        f"correlation {corr:.2f} with already-selected {chosen} — "
                        "taking both would double the same bet"
                    )
                    break
        selected = not excluded
        if selected:
            selected_symbols.append(record.symbol)
        out.append(RankedOpportunity(
            record=record, risk_adjusted_return=round(rar, 4), rank=rank,
            selected=selected, excluded_reason=excluded,
        ))
    return out
