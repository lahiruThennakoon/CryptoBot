"""Drill specs and acknowledgement integrity."""

from cryptobot.readiness.checks import DRILLS, Facts, Status, evaluate, verdict
from cryptobot.readiness.drills import DRILL_SPECS, spec


class TestDrillSpecs:
    def test_every_drill_in_checks_has_a_spec(self):
        """A checklist item with no instructions is unusable."""
        missing = [d for d in DRILLS if d not in DRILL_SPECS]
        assert missing == [], f"drills without instructions: {missing}"

    def test_no_orphan_specs(self):
        extra = [name for name in DRILL_SPECS if name not in DRILLS]
        assert extra == [], f"specs for unknown drills: {extra}"

    def test_specs_are_actionable(self):
        for name, s in DRILL_SPECS.items():
            assert len(s.how) >= 2, f"{name}: needs real steps"
            assert len(s.why) > 40, f"{name}: must explain why it matters"
            assert len(s.pass_criteria) > 30, f"{name}: needs a pass criterion"
            assert s.title and s.name == name

    def test_lookup_helper(self):
        assert spec("emergency_stop") is not None
        assert spec("not_a_drill") is None


class TestAcknowledgementsFeedReadiness:
    def _facts(self, drills: dict[str, bool]) -> Facts:
        return Facts(
            mode="paper", api_secret_is_default=False, gitignore_covers_env=True,
            env_example_has_secrets=False, testnet_keys_configured=True,
            paper_trading_days=120, closed_paper_trades=150, paper_net_pnl=250.0,
            max_drawdown_pct=8.0, db_reachable=True, redis_reachable=True,
            manual_drills=drills,
        )

    def test_unacknowledged_drills_remain_manual(self):
        results = evaluate(self._facts({}))
        drill_checks = [r for r in results if r.name.startswith("drill:")]
        assert drill_checks and all(r.status is Status.MANUAL for r in drill_checks)

    def test_acknowledged_drills_pass(self):
        results = evaluate(self._facts(dict.fromkeys(DRILLS, True)))
        drill_checks = [r for r in results if r.name.startswith("drill:")]
        assert all(r.status is Status.PASS for r in drill_checks)

    def test_partial_acknowledgement_reflected(self):
        acked = {DRILLS[0]: True}
        results = evaluate(self._facts(acked))
        by_name = {r.name: r for r in results if r.name.startswith("drill:")}
        assert by_name[f"drill: {DRILLS[0]}"].status is Status.PASS
        assert by_name[f"drill: {DRILLS[1]}"].status is Status.MANUAL

    def test_acknowledging_drills_never_implies_live_approval(self):
        """Even with every drill ticked, the verdict stays 'owner review'."""
        ready, summary = verdict(evaluate(self._facts(dict.fromkeys(DRILLS, True))))
        assert ready
        assert "READY FOR OWNER REVIEW" in summary
        assert "not guarantee" in summary