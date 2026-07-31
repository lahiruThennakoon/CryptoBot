"""Walk-forward evaluation and cost-sensitivity analysis.

Walk-forward: the strategy is evaluated on successive out-of-sample windows;
each test window's bars were never used to tune anything evaluated on it.
For fixed-parameter rule strategies this measures stability across periods;
when a param grid is supplied, params are selected on the train window only
(by expectancy after costs) and applied to the following test window.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from cryptobot.backtest.engine import BacktestEngine, SimpleRules
from cryptobot.backtest.metrics import Report, compute_report
from cryptobot.costs.model import CostModel
from cryptobot.risk.engine import BasicRiskEngine
from cryptobot.strategies.base import BarLike, Strategy

StrategyFactory = Callable[..., Strategy]


@dataclass
class WindowResult:
    start_index: int
    end_index: int
    chosen_params: dict[str, Any]
    report: Report


@dataclass
class WalkForwardResult:
    windows: list[WindowResult] = field(default_factory=list)

    @property
    def positive_windows(self) -> int:
        return sum(1 for w in self.windows if w.report.net_return_pct > 0)

    @property
    def total_windows(self) -> int:
        return len(self.windows)

    def summary(self) -> str:
        lines = [f"Walk-forward: {self.positive_windows}/{self.total_windows} windows positive"]
        for w in self.windows:
            lines.append(
                f"  bars {w.start_index}-{w.end_index}: net {w.report.net_return_pct:+.2f}% "
                f"dd {w.report.max_drawdown_pct:.2f}% trades {w.report.n_trades} "
                f"params {w.chosen_params or 'default'}"
            )
        lines.append("note: window stability is evidence of robustness, not a guarantee.")
        return "\n".join(lines)


def walk_forward(
    bars: Sequence[BarLike],
    strategy_factory: StrategyFactory,
    train_bars: int,
    test_bars: int,
    timeframe: str = "1h",
    param_grid: Sequence[dict[str, Any]] | None = None,
    costs: CostModel | None = None,
    risk: BasicRiskEngine | None = None,
    rules: SimpleRules | None = None,
    initial_equity: float = 10_000.0,
) -> WalkForwardResult:
    result = WalkForwardResult()
    costs = costs or CostModel()
    step = test_bars
    start = 0
    while start + train_bars + test_bars <= len(bars):
        train = bars[start : start + train_bars]
        test = bars[start + train_bars : start + train_bars + test_bars]

        chosen: dict[str, Any] = {}
        if param_grid:
            best_score = float("-inf")
            for params in param_grid:
                engine = BacktestEngine(costs=costs, risk=risk, rules=rules,
                                        initial_equity=initial_equity)
                try:
                    rep = compute_report(engine.run(train, strategy_factory(**params)), timeframe)
                except ValueError:
                    continue
                score = (rep.expectancy or float("-inf")) if rep.n_trades >= 3 else float("-inf")
                if score > best_score:
                    best_score, chosen = score, params

        engine = BacktestEngine(costs=costs, risk=risk, rules=rules,
                                initial_equity=initial_equity)
        report = compute_report(engine.run(test, strategy_factory(**chosen)), timeframe)
        result.windows.append(WindowResult(
            start_index=start + train_bars,
            end_index=start + train_bars + test_bars,
            chosen_params=chosen,
            report=report,
        ))
        start += step
    return result


def sensitivity_analysis(
    bars: Sequence[BarLike],
    strategy_factory: StrategyFactory,
    timeframe: str = "1h",
    base_costs: CostModel | None = None,
    fee_multipliers: Sequence[float] = (1.0, 1.5, 2.0),
    slippage_multipliers: Sequence[float] = (1.0, 2.0, 3.0),
    initial_equity: float = 10_000.0,
) -> dict[tuple[float, float], Report]:
    """Re-run the backtest under stressed costs. A strategy whose edge
    disappears at 1.5× fees has no real edge."""
    base = base_costs or CostModel()
    out: dict[tuple[float, float], Report] = {}
    for fm in fee_multipliers:
        for sm in slippage_multipliers:
            engine = BacktestEngine(costs=base.stressed(fm, sm), initial_equity=initial_equity)
            out[(fm, sm)] = compute_report(engine.run(bars, strategy_factory()), timeframe)
    return out
