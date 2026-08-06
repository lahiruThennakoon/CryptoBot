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

LEARNING_GATES = Gates(
    buy_threshold=0.22,
    strong_buy_threshold=0.40,
    max_spread_fraction=0.002,
)


def apply_learning_risk(base: RiskConfig) -> RiskConfig:
    return replace(base, min_confidence=0.45, max_trades_per_day=8)


def apply_learning_costs(base: CostModel) -> CostModel:
    return replace(base, safety_margin=0.0005)
