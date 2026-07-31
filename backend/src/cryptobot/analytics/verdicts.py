"""Plain-language verdicts on backtest reports.

Rules: never oversell, always name the comparison baselines, flag samples too
small to judge, and treat 'no trades' as information rather than failure.
"""

from __future__ import annotations

from dataclasses import dataclass

from cryptobot.backtest.metrics import Report

MIN_TRADES_TO_JUDGE = 20


@dataclass(frozen=True)
class Verdict:
    grade: str        # "no_edge" | "inconclusive" | "weak" | "promising" | "no_trades"
    headline: str
    detail: str


def judge(report: Report) -> Verdict:
    if report.n_trades == 0:
        return Verdict(
            "no_trades",
            "Never found a qualifying setup",
            "Every potential trade failed at least one safety check (see the "
            "rejection reasons). This can mean the market offered nothing, or the "
            "strategy's conditions are too strict for this timeframe — either way, "
            "no fees were burned finding out.",
        )
    if report.n_trades < MIN_TRADES_TO_JUDGE:
        return Verdict(
            "inconclusive",
            f"Too few trades to judge ({report.n_trades})",
            f"Fewer than {MIN_TRADES_TO_JUDGE} trades is a sample where luck "
            "dominates skill. The numbers below are shown for transparency, not as "
            "evidence in either direction.",
        )
    if report.net_return_pct <= 0:
        return Verdict(
            "no_edge",
            f"Lost {abs(report.net_return_pct):.2f}% after costs",
            f"Across {report.n_trades} trades, fees ({report.total_fees:.2f}) and "
            f"slippage ({report.total_slippage:.2f}) consumed more than the "
            "strategy earned. On this evidence it does not deserve real money.",
        )
    if not report.beat_buy_hold:
        return Verdict(
            "weak",
            f"Made {report.net_return_pct:.2f}% — but simply holding made "
            f"{report.buy_hold_return_pct:.2f}%",
            "The strategy was profitable but a zero-effort buy-and-hold of the same "
            "asset did better. Trading only earns its complexity when it beats both "
            "doing nothing and simply holding. Its lower drawdown "
            f"({report.max_drawdown_pct:.1f}%) may still have value if smoothness "
            "matters to you.",
        )
    return Verdict(
        "promising",
        f"Made {report.net_return_pct:.2f}% and beat holding "
        f"({report.buy_hold_return_pct:.2f}%)",
        "Positive after all costs and ahead of buy-and-hold — worth deeper "
        "verification: check the walk-forward windows are consistently positive and "
        "the edge survives the higher-cost sensitivity runs before trusting it. "
        "Past performance still guarantees nothing.",
    )
