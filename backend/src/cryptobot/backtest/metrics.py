"""Backtest performance metrics.

A high win rate is NOT treated as evidence of profitability — expectancy,
drawdown and risk-adjusted metrics are the primary measures. VaR is reported
with its limitations stated (historical, assumes the sample generalizes).
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from cryptobot.backtest.engine import BacktestResult

BARS_PER_YEAR = {"1m": 525_600, "5m": 105_120, "15m": 35_040, "1h": 8_760, "4h": 2_190, "1d": 365}


@dataclass
class Report:
    net_return_pct: float = 0.0
    gross_return_pct: float = 0.0
    total_fees: float = 0.0
    total_slippage: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe: float | None = None
    sortino: float | None = None
    profit_factor: float | None = None
    win_rate: float | None = None
    avg_win: float | None = None
    avg_loss: float | None = None
    expectancy: float | None = None       # mean net pnl per trade
    n_trades: int = 0
    exposure_time_pct: float = 0.0
    max_consecutive_losses: int = 0
    var_95_pct: float | None = None       # historical 1-bar VaR; see `notes`
    regime_distribution: dict[str, float] = field(default_factory=dict)  # % of bars
    by_regime: dict[str, dict[str, float]] = field(default_factory=dict)
    by_month: dict[str, float] = field(default_factory=dict)
    exit_reasons: dict[str, int] = field(default_factory=dict)
    rejections: dict[str, int] = field(default_factory=dict)
    buy_hold_return_pct: float = 0.0
    no_trade_return_pct: float = 0.0
    beat_buy_hold: bool = False
    halted: bool = False
    halt_reason: str = ""
    notes: tuple[str, ...] = (
        "Backtest results are estimates, not guarantees; future performance may differ.",
        "VaR is historical and understates tail risk when the sample lacks extreme events.",
        "Win rate alone is not evidence of profitability; judge expectancy and drawdown.",
    )


def compute_report(result: BacktestResult, timeframe: str = "1h") -> Report:
    r = Report()
    eq = result.equity_curve
    if not eq:
        return r
    initial = result.initial_equity
    final = eq[-1]
    r.net_return_pct = (final / initial - 1) * 100
    gross_final = final + result.total_fees + result.total_slippage
    r.gross_return_pct = (gross_final / initial - 1) * 100
    r.total_fees = result.total_fees
    r.total_slippage = result.total_slippage
    r.n_trades = len(result.trades)
    r.halted, r.halt_reason = result.halted, result.halt_reason
    r.exposure_time_pct = 100 * result.bars_in_position / len(eq) if eq else 0.0

    # drawdown
    peak, max_dd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            max_dd = max(max_dd, (peak - v) / peak)
    r.max_drawdown_pct = max_dd * 100

    # per-bar returns → sharpe / sortino / VaR
    rets = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq)) if eq[i - 1] > 0]
    if len(rets) >= 2:
        mean = sum(rets) / len(rets)
        var = sum((x - mean) ** 2 for x in rets) / (len(rets) - 1)
        std = math.sqrt(var)
        ann = math.sqrt(BARS_PER_YEAR.get(timeframe, 8_760))
        if std > 0:
            r.sharpe = mean / std * ann
        downside = [x for x in rets if x < 0]
        if downside:
            dstd = math.sqrt(sum(x**2 for x in downside) / len(downside))
            if dstd > 0:
                r.sortino = mean / dstd * ann
        ordered = sorted(rets)
        r.var_95_pct = -ordered[max(0, int(0.05 * len(ordered)) - 1)] * 100

    # trade stats
    trades = result.trades
    if trades:
        wins = [t.pnl for t in trades if t.pnl > 0]
        losses = [t.pnl for t in trades if t.pnl <= 0]
        r.win_rate = 100 * len(wins) / len(trades)
        r.avg_win = sum(wins) / len(wins) if wins else None
        r.avg_loss = sum(losses) / len(losses) if losses else None
        r.expectancy = sum(t.pnl for t in trades) / len(trades)
        gross_profit = sum(wins)
        gross_loss = -sum(losses)
        r.profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
        streak = worst = 0
        for t in trades:
            streak = streak + 1 if t.pnl <= 0 else 0
            worst = max(worst, streak)
        r.max_consecutive_losses = worst
        for t in trades:
            r.exit_reasons[t.exit_reason] = r.exit_reasons.get(t.exit_reason, 0) + 1

        by_regime: dict[str, list[float]] = defaultdict(list)
        for t in trades:
            by_regime[t.regime_at_entry].append(t.pnl)
        r.by_regime = {
            k: {"trades": len(v), "net_pnl": sum(v),
                "win_rate": 100 * sum(1 for x in v if x > 0) / len(v)}
            for k, v in by_regime.items()
        }
        by_month: dict[str, float] = defaultdict(float)
        for t in trades:
            by_month[t.exit_time.strftime("%Y-%m")] += t.pnl
        r.by_month = dict(sorted(by_month.items()))

    for rej in result.rejected:
        r.rejections[rej.reason_code] = r.rejections.get(rej.reason_code, 0) + 1

    total_regime_bars = sum(result.regime_counts.values())
    if total_regime_bars:
        r.regime_distribution = {
            k: round(100 * v / total_regime_bars, 1)
            for k, v in sorted(result.regime_counts.items())
        }

    if result.buy_hold_curve:
        r.buy_hold_return_pct = (result.buy_hold_curve[-1] / initial - 1) * 100
    r.no_trade_return_pct = 0.0
    r.beat_buy_hold = r.net_return_pct > r.buy_hold_return_pct
    return r


def format_report(r: Report, title: str = "Backtest report") -> str:
    def fmt(v: float | None, suffix: str = "", nd: int = 2) -> str:
        return "n/a" if v is None else f"{v:,.{nd}f}{suffix}"

    lines = [
        "=" * 64, f" {title}", "=" * 64,
        f" Net return          {fmt(r.net_return_pct, '%')}   (gross {fmt(r.gross_return_pct, '%')})",
        f" Buy & hold          {fmt(r.buy_hold_return_pct, '%')}   |  No-trade  0.00%",
        f" Beat buy & hold     {'yes' if r.beat_buy_hold else 'no'}",
        f" Fees / slippage     {fmt(r.total_fees)} / {fmt(r.total_slippage)}",
        f" Max drawdown        {fmt(r.max_drawdown_pct, '%')}",
        f" Sharpe / Sortino    {fmt(r.sharpe)} / {fmt(r.sortino)}",
        f" Profit factor       {fmt(r.profit_factor)}",
        f" Trades              {r.n_trades}  (win rate {fmt(r.win_rate, '%')})",
        f" Avg win / loss      {fmt(r.avg_win)} / {fmt(r.avg_loss)}",
        f" Expectancy/trade    {fmt(r.expectancy)}",
        f" Exposure time       {fmt(r.exposure_time_pct, '%')}",
        f" Max consec losses   {r.max_consecutive_losses}",
        f" 1-bar VaR(95)       {fmt(r.var_95_pct, '%')}  (historical; see notes)",
        f" Halted              {r.halted} {r.halt_reason}",
    ]
    if r.regime_distribution:
        lines.append(" Market regime distribution (% of bars): "
                     + "  ".join(f"{k}={v}%" for k, v in r.regime_distribution.items()))
    if r.by_regime:
        lines.append(" By regime:")
        for k, v in r.by_regime.items():
            lines.append(f"   {k:<12} trades={v['trades']:<4.0f} net={v['net_pnl']:+10.2f} "
                         f"win%={v['win_rate']:.0f}")
    if r.by_month:
        lines.append(" By month:")
        for month, pnl in r.by_month.items():
            lines.append(f"   {month}  {pnl:+10.2f}")
    if r.rejections:
        lines.append(" Rejected signals:")
        for code, n in sorted(r.rejections.items(), key=lambda x: -x[1]):
            lines.append(f"   {code:<24} {n}")
    lines.append("-" * 64)
    for note in r.notes:
        lines.append(f" note: {note}")
    lines.append("=" * 64)
    return "\n".join(lines)
