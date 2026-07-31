"""Screener tests: affordability gating, move-vs-cost, evidence, auto-manage guardrails."""

from cryptobot.pairs.auto_manage import (
    CONSENT_PHRASE,
    AutoManageConfig,
    plan_auto_manage,
)
from cryptobot.pairs.screener import (
    ScreenInput,
    ScreenResult,
    portfolio_advice,
    rank_pairs,
    screen_pair,
)


def good(**overrides) -> ScreenInput:
    base = dict(
        symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT", selectable=True,
        price=60_000.0, atr_pct=1.2, quote_volume_24h=2_000_000_000,
        spread_fraction=0.0002, round_trip_cost_fraction=0.003, min_notional=5.0,
        equity=10_000.0, risk_per_trade=0.005, stop_distance_pct=0.03,
        max_position_pct=0.05, candles_available=800, candles_required=500,
    )
    base.update(overrides)
    return ScreenInput(**base)


class TestAffordability:
    def test_healthy_account_affordable(self):
        r = screen_pair(good())
        assert r.suitable and r.affordable and r.position_notional >= 5

    def test_tiny_account_unaffordable_with_explanation(self):
        r = screen_pair(good(equity=50.0))
        assert not r.suitable and not r.affordable
        assert "unaffordable" in r.blockers[0]
        assert "exchange minimum" in r.blockers[0]

    def test_score_zero_when_unsuitable(self):
        assert screen_pair(good(equity=50.0)).score == 0.0

    def test_non_selectable_short_circuits(self):
        r = screen_pair(good(selectable=False, not_selectable_reason="status is BREAK"))
        assert not r.suitable and "BREAK" in r.blockers[0]

    def test_insufficient_history_blocks_with_command(self):
        r = screen_pair(good(candles_available=50))
        assert not r.suitable
        assert "import-history" in r.blockers[0]


class TestMoveVsCost:
    def test_pair_that_barely_moves_is_rejected(self):
        """The decisive small-account test: typical move must beat trading cost."""
        r = screen_pair(good(atr_pct=0.3, round_trip_cost_fraction=0.003))  # 1.0x
        assert not r.suitable
        assert any("barely moves enough" in b for b in r.blockers)

    def test_thin_margin_flagged_but_allowed(self):
        r = screen_pair(good(atr_pct=0.75, round_trip_cost_fraction=0.003))  # 2.5x
        assert r.suitable
        assert any("thin margin" in x for x in r.reasons)

    def test_healthy_headroom_scores_well(self):
        r = screen_pair(good(atr_pct=2.0, round_trip_cost_fraction=0.003))  # ~6.7x
        assert r.components["tradability"] == 1.0
        assert any("healthy headroom" in x for x in r.reasons)

    def test_unknown_volatility_scored_neutral_not_good(self):
        r = screen_pair(good(atr_pct=None))
        assert r.components["tradability"] < 0.6
        assert any("not favourably" in x for x in r.reasons)

    def test_ratio_reported(self):
        r = screen_pair(good(atr_pct=1.2, round_trip_cost_fraction=0.003))
        assert r.move_to_cost_ratio == 4.0


class TestEvidenceAndDiversification:
    def test_no_evidence_is_neutral_with_warning(self):
        r = screen_pair(good())
        assert r.components["evidence"] == 0.5
        assert any("no backtest evidence" in x for x in r.reasons)

    def test_negative_expectancy_lowers_score_and_says_so(self):
        neg = screen_pair(good(backtest_expectancy_pct=-0.02, backtest_trades=50))
        pos = screen_pair(good(backtest_expectancy_pct=0.02, backtest_trades=50))
        assert neg.components["evidence"] < pos.components["evidence"]
        assert any("lose money here" in x for x in neg.reasons)

    def test_correlated_pair_penalised(self):
        r = screen_pair(good(max_correlation_with_enabled=0.95))
        assert r.components["diversification"] < 0.1
        assert any("doubles" in x for x in r.reasons)

    def test_illiquid_pair_warned(self):
        r = screen_pair(good(quote_volume_24h=20_000_000))
        assert any("low liquidity" in x for x in r.reasons)


class TestRanking:
    def test_deterministic_and_ordered(self):
        inputs = [good(symbol="AAAUSDT", atr_pct=2.0),
                  good(symbol="BBBUSDT", atr_pct=0.8),
                  good(symbol="CCCUSDT", atr_pct=1.5)]
        a = rank_pairs(inputs)
        b = rank_pairs(inputs)
        assert [r.symbol for r in a] == [r.symbol for r in b]
        suitable = [r for r in a if r.suitable]
        assert suitable[0].symbol == "AAAUSDT"
        assert suitable == sorted(suitable, key=lambda r: (-r.score, r.symbol))

    def test_advice_when_nothing_suitable_is_honest(self):
        results = [screen_pair(good(equity=30.0))]
        advice = portfolio_advice(results, 30.0, 3)
        assert "real answer, not a failure" in advice
        assert "Taking more risk does not" in advice or "taking more risk does not" in advice

    def test_advice_never_promises_profit(self):
        advice = portfolio_advice([screen_pair(good())], 10_000, 3)
        assert "NOT 'will be profitable'" in advice


class TestAutoManageGuardrails:
    def _ranked(self) -> list[ScreenResult]:
        return [
            ScreenResult(symbol="AAAUSDT", suitable=True, score=0.80, affordable=True),
            ScreenResult(symbol="BBBUSDT", suitable=True, score=0.70, affordable=True),
            ScreenResult(symbol="CCCUSDT", suitable=False, score=0.0, affordable=True,
                         blockers=["barely moves"]),
        ]

    def test_disabled_by_default_changes_nothing(self):
        plan = plan_auto_manage(AutoManageConfig(), self._ranked(), {"AAAUSDT"}, set())
        assert plan.is_noop
        assert "not authorised" in plan.blocked_reason
        assert plan.unchanged == ["AAAUSDT"]

    def test_consent_phrase_required(self):
        config = AutoManageConfig(enabled=True, consent_phrase="sure")
        assert not config.authorised
        assert plan_auto_manage(config, self._ranked(), set(), set()).is_noop

    def test_requires_positive_evidence_to_enable(self):
        config = AutoManageConfig(enabled=True, consent_phrase=CONSENT_PHRASE)
        plan = plan_auto_manage(config, self._ranked(), set(), set(), evidence_positive={})
        assert not plan.enable        # no evidence → nothing auto-enabled

    def test_enables_only_evidenced_candidates(self):
        config = AutoManageConfig(enabled=True, consent_phrase=CONSENT_PHRASE,
                                  max_active_pairs=2)
        plan = plan_auto_manage(config, self._ranked(), set(), set(),
                                evidence_positive={"AAAUSDT": True, "BBBUSDT": True})
        assert [s for s, _ in plan.enable] == ["AAAUSDT", "BBBUSDT"]
        assert all("positive backtest evidence" in r for _, r in plan.enable)

    def test_respects_max_active_pairs(self):
        config = AutoManageConfig(enabled=True, consent_phrase=CONSENT_PHRASE,
                                  max_active_pairs=1)
        plan = plan_auto_manage(config, self._ranked(), set(), set(),
                                evidence_positive={"AAAUSDT": True, "BBBUSDT": True})
        assert len(plan.enable) == 1

    def test_never_disables_pair_with_open_position(self):
        config = AutoManageConfig(enabled=True, consent_phrase=CONSENT_PHRASE)
        plan = plan_auto_manage(config, self._ranked(), {"CCCUSDT"}, {"CCCUSDT"})
        assert "CCCUSDT" not in [s for s, _ in plan.disable]
        assert "CCCUSDT" in plan.unchanged

    def test_disables_pair_that_stopped_qualifying(self):
        config = AutoManageConfig(enabled=True, consent_phrase=CONSENT_PHRASE)
        plan = plan_auto_manage(config, self._ranked(), {"CCCUSDT"}, set())
        assert ("CCCUSDT", "no longer passes screening") in plan.disable

    def test_hysteresis_keeps_marginal_pairs(self):
        ranked = [ScreenResult(symbol="AAAUSDT", suitable=True, score=0.50, affordable=True)]
        config = AutoManageConfig(enabled=True, consent_phrase=CONSENT_PHRASE)
        plan = plan_auto_manage(config, ranked, {"AAAUSDT"}, set())
        assert "AAAUSDT" in plan.unchanged      # above keep threshold, below enable
        assert not plan.disable