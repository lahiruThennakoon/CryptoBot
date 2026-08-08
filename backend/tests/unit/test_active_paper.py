from cryptobot.config.active_paper import (
    ACTIVE_PAPER_GATES,
    apply_active_paper_costs,
    apply_active_paper_risk,
    build_active_paper_strategies,
)
from cryptobot.costs.model import CostModel
from cryptobot.risk.engine import RiskConfig


def test_active_paper_gates_are_relaxed() -> None:
    assert ACTIVE_PAPER_GATES.buy_threshold <= 0.10
    assert ACTIVE_PAPER_GATES.skip_cost_gate is True
    assert ACTIVE_PAPER_GATES.max_spread_fraction >= 0.006


def test_active_paper_risk_higher_and_frequent() -> None:
    cfg = apply_active_paper_risk(RiskConfig(fixed_entry_notional_usd=10.0))
    assert cfg.min_confidence <= 0.25
    assert cfg.max_trades_per_day >= 30
    assert cfg.risk_per_trade >= 0.01
    assert cfg.max_position_pct >= 0.12
    assert cfg.max_positions >= 4


def test_active_paper_strategies_are_normal_roster() -> None:
    names = {s.spec.name for s in build_active_paper_strategies()}
    assert "learning_pulse" not in names
    assert "ma_trend" in names
    assert "momentum_volume" in names
    assert "mtf_trend" in names


def test_active_paper_strategies_use_aggressive_params() -> None:
    by_name = {s.spec.name: s for s in build_active_paper_strategies()}
    assert by_name["momentum_volume"].spec.params["min_return"] <= 0.003
    assert by_name["rsi_reversion"].spec.params["oversold"] >= 40.0
    assert by_name["ma_trend"].spec.params["fast"] <= 10


def test_active_paper_costs_drop_safety_margin() -> None:
    costs = apply_active_paper_costs(CostModel())
    assert costs.safety_margin == 0.0
