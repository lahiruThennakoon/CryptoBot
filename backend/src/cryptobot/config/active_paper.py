"""Active paper profile — frequent real-strategy trades with simulated costs.

For operators who want paper PnL that includes fees/spread while still seeing
regular entries from the normal strategy roster (no learning_pulse). Not for
live trading or graduation evidence on its own — pair with backtests for GC-4.
"""

from __future__ import annotations

from dataclasses import replace

from cryptobot.costs.model import CostModel
from cryptobot.decision.scoring import Gates
from cryptobot.execution.policy import ExecutionPolicy, OrderStyle
from cryptobot.risk.engine import RiskConfig
from cryptobot.strategies import STRATEGY_REGISTRY
from cryptobot.strategies.base import Strategy
from cryptobot.strategies.breakout_volatility import BreakoutVolatilityStrategy
from cryptobot.strategies.momentum_volume import MomentumVolumeStrategy
from cryptobot.strategies.rsi_reversion import RsiReversionStrategy

ACTIVE_PAPER_GATES = Gates(
    buy_threshold=0.12,
    strong_buy_threshold=0.28,
    max_spread_fraction=0.004,
    require_strategy_entry=True,
    skip_cost_gate=False,
)

ACTIVE_PAPER_POLICY = ExecutionPolicy(entry_style=OrderStyle.MARKET)


def build_active_paper_strategies() -> list[Strategy]:
    """All five baseline strategies with moderately relaxed entry thresholds."""
    return [
        MomentumVolumeStrategy(min_return=0.005, volume_mult=1.1),
        RsiReversionStrategy(oversold=35.0, exit_level=58.0),
        BreakoutVolatilityStrategy(max_vol_rank=0.92),
        STRATEGY_REGISTRY["ma_trend"](),
        STRATEGY_REGISTRY["mtf_trend"](),
    ]


def apply_active_paper_risk(base: RiskConfig) -> RiskConfig:
    return replace(
        base,
        risk_per_trade=0.004,
        max_position_pct=0.06,
        max_trades_per_day=15,
        min_confidence=0.35,
        max_daily_loss_pct=0.05,
    )


def apply_active_paper_costs(base: CostModel) -> CostModel:
    return replace(base, safety_margin=0.0002)
