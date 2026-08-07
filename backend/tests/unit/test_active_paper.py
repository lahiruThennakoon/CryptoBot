from cryptobot.config.active_paper import (
    ACTIVE_PAPER_GATES,
    apply_active_paper_costs,
    apply_active_paper_risk,
    build_active_paper_strategies,
)
from cryptobot.costs.model import CostModel
from cryptobot.risk.engine import RiskConfig


def test_active_paper_gates_are_relaxed() -> None:
    assert ACTIVE_PAPER_GATES.buy_threshold <= 0.15
    assert ACTIVE_PAPER_GATES.skip_cost_gate is False


def test_active_paper_risk_small_and_frequent() -> None:
    cfg = apply_active_paper_risk(RiskConfig(fixed_entry_notional_usd=10.0))
    assert cfg.min_confidence == 0.35
    assert cfg.max_trades_per_day == 15
    assert cfg.risk_per_trade == 0.004


def test_active_paper_strategies_are_normal_roster() -> None:
    names = {s.spec.name for s in build_active_paper_strategies()}
    assert "learning_pulse" not in names
    assert "ma_trend" in names
    assert "momentum_volume" in names


def test_active_paper_costs_keep_fee_gate() -> None:
    costs = apply_active_paper_costs(CostModel())
    assert costs.safety_margin < CostModel().safety_margin
    assert costs.safety_margin > 0
