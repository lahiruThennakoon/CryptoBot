from cryptobot.config.learning_mode import (
    LEARNING_GATES,
    apply_learning_costs,
    apply_learning_risk,
)
from cryptobot.costs.model import CostModel
from cryptobot.risk.engine import RiskConfig


def test_learning_gates_lower_than_default() -> None:
    assert LEARNING_GATES.buy_threshold < 0.35
    assert LEARNING_GATES.strong_buy_threshold < 0.60


def test_apply_learning_risk() -> None:
    cfg = apply_learning_risk(RiskConfig())
    assert cfg.min_confidence == 0.45
    assert cfg.max_trades_per_day == 8


def test_apply_learning_costs() -> None:
    costs = apply_learning_costs(CostModel())
    assert costs.safety_margin < CostModel().safety_margin
