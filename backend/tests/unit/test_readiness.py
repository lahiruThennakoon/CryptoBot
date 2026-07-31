from cryptobot.readiness.checks import DRILLS, Facts, Status, evaluate, verdict


def good_facts() -> Facts:
    return Facts(
        mode="paper",
        api_secret_is_default=False,
        gitignore_covers_env=True,
        env_example_has_secrets=False,
        testnet_keys_configured=True,
        live_keys_configured=False,
        confirm_phrase_set=False,
        paper_trading_days=120,
        closed_paper_trades=150,
        paper_net_pnl=250.0,
        max_drawdown_pct=8.0,
        db_reachable=True,
        redis_reachable=True,
        manual_drills=dict.fromkeys(DRILLS, True),
    )


def by_name(results, name):
    return next(r for r in results if r.name == name)


class TestEvaluate:
    def test_good_facts_have_no_failures(self):
        results = evaluate(good_facts())
        assert not [r for r in results if r.status is Status.FAIL]

    def test_live_mode_fails_hard(self):
        f = good_facts()
        f.mode = "live"
        assert by_name(evaluate(f), "live trading disabled").status is Status.FAIL

    def test_default_api_secret_fails(self):
        f = good_facts()
        f.api_secret_is_default = True
        assert by_name(evaluate(f), "API_SECRET_KEY configured").status is Status.FAIL

    def test_missing_evidence_fails(self):
        f = good_facts()
        f.paper_trading_days = None
        assert by_name(evaluate(f), "paper-trading duration").status is Status.FAIL

    def test_insufficient_paper_days_fails(self):
        f = good_facts()
        f.paper_trading_days = 30
        assert by_name(evaluate(f), "paper-trading duration").status is Status.FAIL

    def test_negative_pnl_fails(self):
        f = good_facts()
        f.paper_net_pnl = -10.0
        assert by_name(evaluate(f), "net paper PnL after costs").status is Status.FAIL

    def test_excess_drawdown_fails(self):
        f = good_facts()
        f.max_drawdown_pct = 22.0
        assert by_name(evaluate(f), "max drawdown").status is Status.FAIL

    def test_unacked_drills_are_manual(self):
        f = good_facts()
        f.manual_drills = {}
        drill_results = [r for r in evaluate(f) if r.name.startswith("drill:")]
        assert all(r.status is Status.MANUAL for r in drill_results)

    def test_premature_live_credentials_warn(self):
        f = good_facts()
        f.live_keys_configured = True
        assert by_name(
            evaluate(f), "live gate factors absent until approval"
        ).status is Status.WARN


class TestVerdict:
    def test_never_says_ready_for_live(self):
        ready, summary = verdict(evaluate(good_facts()))
        assert ready
        assert "READY FOR OWNER REVIEW" in summary
        assert "not guarantee" in summary
        assert "READY FOR LIVE" not in summary.upper().replace("OWNER REVIEW", "")

    def test_any_failure_means_not_ready(self):
        f = good_facts()
        f.gitignore_covers_env = False
        ready, summary = verdict(evaluate(f))
        assert not ready and "NOT READY" in summary

    def test_manual_items_always_reported(self):
        _, summary = verdict(evaluate(good_facts()))
        assert "manual verification" in summary