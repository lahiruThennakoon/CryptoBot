"""Tests for FR-5.4 fixed entry notional sizing."""

from cryptobot.risk.engine import BasicRiskEngine, RiskConfig, RiskState


def _state(equity: float = 200.0) -> RiskState:
    return RiskState(equity=equity, high_water_mark=equity)


class TestFixedNotional:
    def test_caps_position_at_fixed_usd(self):
        eng = BasicRiskEngine(RiskConfig(
            fixed_entry_notional_usd=10.0,
            max_position_pct=1.0,
            max_exposure_pct=1.0,
            risk_per_trade=0.05,
        ))
        d = eng.evaluate_entry(
            _state(200.0), confidence=0.9, price=100.0, stop_price=95.0,
            step_size=0.01, min_notional=5.0,
        )
        assert d.approved
        assert abs(d.qty * 100.0 - 10.0) < 0.01

    def test_rejects_fixed_below_exchange_min(self):
        eng = BasicRiskEngine(RiskConfig(fixed_entry_notional_usd=3.0))
        d = eng.evaluate_entry(
            _state(200.0), confidence=0.9, price=100.0, stop_price=95.0,
            min_notional=5.0,
        )
        assert not d.approved and d.reason_code == "FIXED_NOTIONAL_BELOW_MIN"

    def test_zero_fixed_uses_risk_based(self):
        eng = BasicRiskEngine(RiskConfig(
            fixed_entry_notional_usd=0.0,
            risk_per_trade=0.01,
            max_position_pct=1.0,
            max_exposure_pct=1.0,
        ))
        d = eng.evaluate_entry(
            _state(10_000.0), confidence=0.9, price=100.0, stop_price=90.0,
            step_size=1.0,
        )
        assert d.approved
        assert abs(d.qty - 10.0) < 0.01  # 1% of 10k / $10 stop distance
