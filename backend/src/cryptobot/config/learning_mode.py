"""Relaxed thresholds for testnet learning — more signals, not for live trading.

Learning mode loosens decision and risk gates so operators see entries,
near-misses, and rejections on a small account. Expect more fee drag; results
are not graduation evidence.
"""

from __future__ import annotations

from dataclasses import replace

from cryptobot.costs.model import CostModel
from cryptobot.decision.scoring import Gates
from cryptobot.risk.engine import RiskConfig
from cryptobot.strategies import STRATEGY_REGISTRY
from cryptobot.strategies.base import Strategy
from cryptobot.strategies.breakout_volatility import BreakoutVolatilityStrategy
from cryptobot.strategies.learning_pulse import LearningPulseStrategy
from cryptobot.strategies.momentum_volume import MomentumVolumeStrategy
from cryptobot.strategies.rsi_reversion import RsiReversionStrategy

LEARNING_GATES = Gates(
    buy_threshold=0.15,
    strong_buy_threshold=0.30,
    max_spread_fraction=0.003,
    require_strategy_entry=True,
    skip_cost_gate=True,
)


def build_learning_strategies() -> list[Strategy]:
    """Standard roster with relaxed params plus the learning pulse driver."""
    return [
        MomentumVolumeStrategy(min_return=0.008, volume_mult=1.2),
        RsiReversionStrategy(oversold=40.0, exit_level=60.0),
        BreakoutVolatilityStrategy(max_vol_rank=0.95),
        LearningPulseStrategy(),
        *[STRATEGY_REGISTRY[n]() for n in ("ma_trend", "mtf_trend")],
    ]


def apply_learning_risk(base: RiskConfig) -> RiskConfig:
    return replace(base, min_confidence=0.35, max_trades_per_day=12)


def apply_learning_costs(base: CostModel) -> CostModel:
    return replace(base, safety_margin=0.0)
