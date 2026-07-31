from datetime import UTC, datetime

from cryptobot.session.policy import (
    OvernightPolicy,
    SessionConfig,
    SessionState,
    TargetProtection,
    evaluate_entry_policy,
    session_ended,
    validate_config,
)

MONDAY_NOON = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)   # Monday
SUNDAY_NOON = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


class TestValidation:
    def test_default_config_valid(self):
        assert validate_config(SessionConfig()) == []

    def test_end_before_start_rejected(self):
        problems = validate_config(SessionConfig(session_start_utc="18:00",
                                                 session_end_utc="09:00"))
        assert any("after session start" in p for p in problems)

    def test_no_trading_days_rejected(self):
        assert validate_config(SessionConfig(trading_days=()))

    def test_target_below_cost_floor_rejected(self):
        problems = validate_config(SessionConfig(daily_profit_target_pct=0.001))
        assert any("cost floor" in p for p in problems)

    def test_greedy_target_rejected(self):
        problems = validate_config(SessionConfig(daily_profit_target_pct=0.20))
        assert any("refuses" in p for p in problems)

    def test_sane_target_accepted(self):
        assert validate_config(SessionConfig(daily_profit_target_pct=0.01)) == []


class TestSessionWindow:
    def test_weekday_in_session_allowed(self):
        cfg = SessionConfig(trading_days=(0, 1, 2, 3, 4))
        assert evaluate_entry_policy(cfg, SessionState(), MONDAY_NOON).allowed

    def test_disabled_day_blocked(self):
        cfg = SessionConfig(trading_days=(0, 1, 2, 3, 4))   # weekdays only
        policy = evaluate_entry_policy(cfg, SessionState(), SUNDAY_NOON)
        assert not policy.allowed and policy.reason_code == "OUT_OF_SESSION"

    def test_outside_hours_blocked(self):
        cfg = SessionConfig(session_start_utc="14:00", session_end_utc="18:00")
        policy = evaluate_entry_policy(cfg, SessionState(), MONDAY_NOON)
        assert not policy.allowed and policy.reason_code == "OUT_OF_SESSION"

    def test_session_ended_detection(self):
        cfg = SessionConfig(session_end_utc="10:00")
        assert session_ended(cfg, MONDAY_NOON)


class TestProfitTargetProtection:
    def _state(self, pnl: float) -> SessionState:
        return SessionState(day_start_equity=10_000.0, realized_pnl_today=pnl)

    def test_below_target_normal_trading(self):
        cfg = SessionConfig(daily_profit_target_pct=0.01)
        assert evaluate_entry_policy(cfg, self._state(50.0), MONDAY_NOON).allowed

    def test_stop_trading_default_blocks_new_entries(self):
        cfg = SessionConfig(daily_profit_target_pct=0.01)   # default protection
        policy = evaluate_entry_policy(cfg, self._state(150.0), MONDAY_NOON)
        assert not policy.allowed
        assert policy.reason_code == "PROFIT_TARGET_REACHED"
        assert cfg.target_protection is TargetProtection.STOP_TRADING

    def test_reduce_size_mode(self):
        cfg = SessionConfig(daily_profit_target_pct=0.01,
                            target_protection=TargetProtection.REDUCE_SIZE)
        policy = evaluate_entry_policy(cfg, self._state(150.0), MONDAY_NOON)
        assert policy.allowed and policy.size_factor == 0.5

    def test_raise_confidence_mode(self):
        cfg = SessionConfig(daily_profit_target_pct=0.01,
                            target_protection=TargetProtection.RAISE_CONFIDENCE)
        policy = evaluate_entry_policy(cfg, self._state(150.0), MONDAY_NOON)
        assert policy.allowed and policy.min_confidence_override == 0.8

    def test_exceptional_only_mode(self):
        cfg = SessionConfig(daily_profit_target_pct=0.01,
                            target_protection=TargetProtection.EXCEPTIONAL_ONLY)
        policy = evaluate_entry_policy(cfg, self._state(150.0), MONDAY_NOON)
        assert policy.allowed and policy.min_score_override == 0.75

    def test_loss_never_triggers_protection(self):
        """A losing day must never trip target logic (no revenge mechanics)."""
        cfg = SessionConfig(daily_profit_target_pct=0.01)
        assert evaluate_entry_policy(cfg, self._state(-500.0), MONDAY_NOON).allowed


class TestOvernight:
    def test_policies_exist(self):
        assert OvernightPolicy.HOLD.value == "hold"
        assert OvernightPolicy.CLOSE_AT_SESSION_END.value == "close_at_session_end"