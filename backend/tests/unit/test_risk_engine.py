from datetime import date

from cryptobot.risk.engine import BasicRiskEngine, RiskConfig, RiskState


def state(equity=10_000.0, **kw) -> RiskState:
    s = RiskState(equity=equity, high_water_mark=equity)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def engine(**kw) -> BasicRiskEngine:
    return BasicRiskEngine(RiskConfig(**kw))


class TestVeto:
    def test_approves_valid_entry(self):
        d = engine().evaluate_entry(state(), confidence=0.9, price=100.0, stop_price=95.0)
        assert d.approved and d.qty > 0

    def test_rejects_missing_stop(self):
        d = engine().evaluate_entry(state(), confidence=0.9, price=100.0, stop_price=None)
        assert not d.approved and d.reason_code == "NO_STOP"

    def test_rejects_stop_above_price(self):
        d = engine().evaluate_entry(state(), confidence=0.9, price=100.0, stop_price=101.0)
        assert not d.approved and d.reason_code == "INVALID_STOP"

    def test_rejects_low_confidence(self):
        d = engine(min_confidence=0.6).evaluate_entry(
            state(), confidence=0.5, price=100.0, stop_price=95.0)
        assert d.reason_code == "LOW_CONFIDENCE"

    def test_rejects_max_positions(self):
        d = engine(max_positions=1).evaluate_entry(
            state(open_positions=1), confidence=0.9, price=100.0, stop_price=95.0)
        assert d.reason_code == "MAX_POSITIONS"

    def test_rejects_max_trades_per_day(self):
        d = engine(max_trades_per_day=2).evaluate_entry(
            state(trades_today=2), confidence=0.9, price=100.0, stop_price=95.0)
        assert d.reason_code == "MAX_TRADES_PER_DAY"

    def test_rejects_when_exposure_full(self):
        s = state(exposure_notional=2500.0)
        d = engine(max_exposure_pct=0.25).evaluate_entry(
            s, confidence=0.9, price=100.0, stop_price=95.0)
        assert d.reason_code == "MAX_EXPOSURE"


class TestHalts:
    def test_daily_loss_halts(self):
        s = state(daily_realized_pnl=-250.0)   # 2.5% of 10k
        d = engine(max_daily_loss_pct=0.02).evaluate_entry(
            s, confidence=0.9, price=100.0, stop_price=95.0)
        assert d.reason_code == "DAILY_LOSS_LIMIT"
        assert s.halted

    def test_halt_is_sticky_until_review(self):
        s = state(daily_realized_pnl=-250.0)
        e = engine(max_daily_loss_pct=0.02)
        e.evaluate_entry(s, confidence=0.9, price=100.0, stop_price=95.0)
        s.daily_realized_pnl = 0.0             # even after PnL resets…
        d = e.evaluate_entry(s, confidence=0.9, price=100.0, stop_price=95.0)
        assert d.reason_code == "HALTED"       # …halt persists until explicit review

    def test_drawdown_halts(self):
        s = state(equity=8_000.0)
        s.high_water_mark = 10_000.0
        d = engine(max_drawdown_pct=0.15).evaluate_entry(
            s, confidence=0.9, price=100.0, stop_price=95.0)
        assert d.reason_code == "MAX_DRAWDOWN"

    def test_consecutive_losses_halt(self):
        s = state(consecutive_losses=5)
        d = engine(max_consecutive_losses=5).evaluate_entry(
            s, confidence=0.9, price=100.0, stop_price=95.0)
        assert d.reason_code == "CONSECUTIVE_LOSSES"


class TestSizing:
    def test_qty_risks_configured_fraction(self):
        d = engine(risk_per_trade=0.01, max_position_pct=1.0, max_exposure_pct=1.0).evaluate_entry(
            state(), confidence=0.9, price=100.0, stop_price=90.0)
        assert abs(d.qty * (100.0 - 90.0) - 100.0) < 1.0   # ~1% of 10k at risk

    def test_position_cap_applies(self):
        d = engine(risk_per_trade=0.10, max_position_pct=0.05).evaluate_entry(
            state(), confidence=0.9, price=100.0, stop_price=99.5)
        assert d.qty * 100.0 <= 10_000 * 0.05 + 1e-6

    def test_min_notional_rejects_dust(self):
        d = engine(risk_per_trade=0.0001, max_position_pct=0.0001).evaluate_entry(
            state(equity=100.0), confidence=0.9, price=100.0, stop_price=95.0,
            min_notional=5.0)
        assert d.reason_code == "SIZE_BELOW_MIN_NOTIONAL"


class TestStateRolls:
    def test_day_roll_resets_daily_counters(self):
        s = state(trades_today=5, daily_realized_pnl=-100.0)
        s.roll_day(date(2026, 1, 2))
        assert s.trades_today == 0 and s.daily_realized_pnl == 0.0

    def test_record_close_tracks_streak(self):
        s = state()
        s.record_close(-10)
        s.record_close(-10)
        assert s.consecutive_losses == 2
        s.record_close(+10)
        assert s.consecutive_losses == 0