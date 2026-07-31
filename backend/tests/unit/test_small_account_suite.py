"""Tests for the small-account suite: costs, sizing, maker policy, awareness, wisdom."""

from datetime import UTC, datetime

from cryptobot.analytics.awareness import (
    behaviour_flags,
    execution_divergence,
    growth_outlook,
    recovery_math,
)
from cryptobot.analytics.cost_microscope import (
    CostInputs,
    SizingInputs,
    analyse_costs,
    check_sizing,
)
from cryptobot.costs.model import CostModel
from cryptobot.execution.policy import (
    ExecutionPolicy,
    OrderStyle,
    effective_costs,
    limit_price_for_entry,
    savings_estimate,
)
from cryptobot.risk.engine import RiskConfig
from cryptobot.risk.small_account import (
    apply_small_account_guardrails,
    evaluate_wisdom_rules,
)


class TestCostMicroscope:
    def test_small_account_costs_are_material(self):
        r = analyse_costs(CostInputs(equity=300, price=60_000, trades_per_day=3))
        assert r.round_trip_cost_usd > 0
        assert r.breakeven_move_pct > 0.2          # must move >0.2% to break even
        assert r.monthly_cost_pct_of_equity > 0

    def test_high_frequency_warning(self):
        r = analyse_costs(CostInputs(equity=300, price=60_000, trades_per_day=10))
        assert any("per month" in w for w in r.warnings)

    def test_below_min_notional_warning(self):
        r = analyse_costs(CostInputs(equity=50, price=60_000, position_pct=0.05,
                                     min_notional=5.0))
        assert any("below the exchange minimum" in w for w in r.warnings)

    def test_maker_is_cheaper_than_taker(self):
        r = analyse_costs(CostInputs(equity=1000, price=60_000))
        assert r.maker_round_trip_cost_usd < r.round_trip_cost_usd
        assert r.maker_saving_usd_per_trade > 0

    def test_bnb_discount_reduces_cost(self):
        base = analyse_costs(CostInputs(equity=1000, price=60_000))
        disc = analyse_costs(CostInputs(equity=1000, price=60_000, bnb_discount=0.25))
        assert disc.round_trip_cost_usd < base.round_trip_cost_usd

    def test_summary_is_plain_language(self):
        r = analyse_costs(CostInputs(equity=300, price=60_000))
        assert "break" in r.plain_summary.lower() or "move" in r.plain_summary.lower()
        assert "$" in r.plain_summary


class TestSizingCheck:
    def test_viable_settings_pass(self):
        r = check_sizing(SizingInputs(equity=10_000, price=60_000, risk_per_trade=0.005,
                                      stop_distance_pct=0.03))
        assert r.feasible and r.notional >= 5

    def test_impossible_settings_detected_with_remedy(self):
        r = check_sizing(SizingInputs(equity=100, price=60_000, risk_per_trade=0.001,
                                      stop_distance_pct=0.05, min_notional=5.0))
        assert not r.feasible
        assert "minimum" in r.blocking_reason
        assert r.min_equity_for_current_settings and r.min_equity_for_current_settings > 100

    def test_position_cap_respected(self):
        r = check_sizing(SizingInputs(equity=10_000, price=60_000, risk_per_trade=0.10,
                                      stop_distance_pct=0.01, max_position_pct=0.05))
        assert r.notional <= 10_000 * 0.05 + 1

    def test_rejects_nonsense_inputs(self):
        assert not check_sizing(SizingInputs(equity=0, price=60_000)).feasible


class TestExecutionPolicy:
    def test_maker_policy_lowers_round_trip_costs(self):
        costs = CostModel()
        maker = ExecutionPolicy(entry_style=OrderStyle.MAKER_LIMIT)
        assert effective_costs(costs, maker).round_trip_fraction < costs.round_trip_fraction

    def test_bnb_discount_applies_to_both_styles(self):
        costs = CostModel()
        p = ExecutionPolicy(bnb_discount=0.25)
        assert effective_costs(costs, p).taker_fee < costs.taker_fee

    def test_limit_price_rests_below_market(self):
        assert limit_price_for_entry(100.0, ExecutionPolicy(limit_offset_bps=10)) < 100.0

    def test_savings_estimate_positive_for_maker(self):
        s = savings_estimate(CostModel(), ExecutionPolicy(entry_style=OrderStyle.MAKER_LIMIT),
                             notional=1000, trades_per_month=60)
        assert s["per_trade_usd"] > 0 and s["per_month_usd"] > 0
        assert s["policy_round_trip_pct"] < s["taker_round_trip_pct"]

    def test_market_policy_unchanged_costs(self):
        costs = CostModel()
        same = effective_costs(costs, ExecutionPolicy())
        assert abs(same.round_trip_fraction - costs.round_trip_fraction) < 1e-12


class TestGuardrails:
    def test_tiny_account_gets_strictest_rules(self):
        g = apply_small_account_guardrails(RiskConfig(), 300.0, CostModel().round_trip_fraction)
        assert g.max_trades_per_day <= 4
        assert g.config.max_positions <= 2
        assert g.min_expected_edge > CostModel().round_trip_fraction
        assert g.adjustments

    def test_mid_account_moderate_rules(self):
        g = apply_small_account_guardrails(RiskConfig(), 3000.0, CostModel().round_trip_fraction)
        assert g.max_trades_per_day <= 8

    def test_large_account_untouched(self):
        g = apply_small_account_guardrails(RiskConfig(), 100_000.0,
                                           CostModel().round_trip_fraction)
        assert g.config.max_trades_per_day == RiskConfig().max_trades_per_day

    def test_min_notional_forces_position_cap_with_explanation(self):
        g = apply_small_account_guardrails(RiskConfig(), 60.0,
                                           CostModel().round_trip_fraction, min_notional=5.0)
        assert any("exchange minimum" in a for a in g.adjustments)


class TestWisdomRules:
    def _kwargs(self, **overrides):
        base = dict(
            expected_net_return=0.01, round_trip_cost_fraction=0.003,
            stop_distance_pct=0.03, take_profit_pct=0.06, spread_fraction=0.0004,
            quote_volume_24h=2_000_000_000, hours_since_last_loss_on_pair=5.0,
            position_count=1, correlated_position_exists=False,
            is_averaging_down=False, equity_fraction_at_risk=0.005,
        )
        base.update(overrides)
        return base

    def test_healthy_trade_passes_all(self):
        assert evaluate_wisdom_rules(**self._kwargs()).all_passed

    def test_negative_edge_blocked(self):
        r = evaluate_wisdom_rules(**self._kwargs(expected_net_return=-0.001))
        assert not r.all_passed
        assert any(c.code == "COSTS_FIRST" for c in r.blocking)

    def test_averaging_down_blocked(self):
        r = evaluate_wisdom_rules(**self._kwargs(is_averaging_down=True))
        assert any(c.code == "NEVER_AVERAGE_DOWN" for c in r.blocking)

    def test_oversized_risk_blocked(self):
        r = evaluate_wisdom_rules(**self._kwargs(equity_fraction_at_risk=0.10))
        assert any(c.code == "SURVIVE_FIRST" for c in r.blocking)

    def test_revenge_trade_blocked(self):
        r = evaluate_wisdom_rules(**self._kwargs(hours_since_last_loss_on_pair=0.1))
        assert any(c.code == "COOLDOWN_AFTER_LOSS" for c in r.blocking)

    def test_illiquid_pair_blocked(self):
        r = evaluate_wisdom_rules(**self._kwargs(quote_volume_24h=1_000_000))
        assert any(c.code == "LIQUIDITY_MATTERS" for c in r.blocking)

    def test_correlated_exposure_blocked(self):
        r = evaluate_wisdom_rules(**self._kwargs(correlated_position_exists=True))
        assert any(c.code == "CORRELATION_IS_CONCENTRATION" for c in r.blocking)

    def test_every_rule_states_its_principle(self):
        for check in evaluate_wisdom_rules(**self._kwargs()).checks:
            assert len(check.principle) > 40   # a real explanation, not a label


class TestAwareness:
    def test_recovery_asymmetry(self):
        r = recovery_math(10_000, 8_000)
        assert abs(r.drawdown_pct - 20.0) < 0.01
        assert abs(r.gain_needed_pct - 25.0) < 0.01
        assert "NOT a reason to increase risk" in r.message

    def test_no_drawdown_message(self):
        assert recovery_math(10_000, 10_000).gain_needed_pct == 0.0

    def test_growth_outlook_flags_small_samples(self):
        o = growth_outlook([0.5, -0.3, 0.8], 1000, horizon_trades=20, simulations=200)
        assert not o.statistically_meaningful
        assert any("too few" in c for c in o.caveats)

    def test_growth_outlook_negative_expectancy_warned(self):
        o = growth_outlook([-0.5] * 40, 1000, horizon_trades=20, simulations=200)
        assert any("negative" in c for c in o.caveats)
        assert o.p50_equity is not None and o.p50_equity < 1000

    def test_growth_outlook_is_deterministic(self):
        a = growth_outlook([0.4, -0.2] * 20, 1000, simulations=300)
        b = growth_outlook([0.4, -0.2] * 20, 1000, simulations=300)
        assert a.p50_equity == b.p50_equity      # seeded

    def test_growth_outlook_never_promises(self):
        o = growth_outlook([0.4, -0.2] * 20, 1000, simulations=200)
        assert "promised" in o.message or "not a forecast" in " ".join(o.caveats).lower() \
            or any("bad tail" in c for c in o.caveats)

    def test_divergence_needs_samples(self):
        assert execution_divergence(0.003, [0.001]).verdict == "insufficient_data"

    def test_divergence_detects_optimistic_model(self):
        r = execution_divergence(0.001, [0.005] * 10)
        assert r.verdict == "model_optimistic"
        assert "optimistic" in r.message

    def test_divergence_accepts_realistic_model(self):
        r = execution_divergence(0.003, [0.003] * 10)
        assert r.verdict == "model_realistic"

    def test_behaviour_flags_loosening_pattern(self):
        now = datetime.now(UTC)
        changes = [(now, "update_risk_setting", "loosened") for _ in range(3)]
        flags = behaviour_flags(changes, consecutive_losses=4)
        codes = {f.code for f in flags}
        assert "FREQUENT_LOOSENING" in codes
        assert "LOOSENING_AFTER_LOSSES" in codes

    def test_behaviour_quiet_when_steady(self):
        assert behaviour_flags([], 0, 0)[0].code == "STEADY"


class TestCryptoKnowledgeBase:
    def test_corpus_has_breadth_and_no_predictions(self):
        from cryptobot.ai.crypto_kb import CRYPTO_KNOWLEDGE, as_chunks

        topics = {t for t, _, _ in CRYPTO_KNOWLEDGE}
        assert {"market-structure", "costs", "indicators", "strategy", "risk",
                "operations"} <= topics
        assert len(CRYPTO_KNOWLEDGE) >= 25
        banned = ["will rise", "will fall", "guaranteed profit", "price target",
                  "sure thing"]
        for _, title, text in CRYPTO_KNOWLEDGE:
            low = (title + " " + text).lower()
            for phrase in banned:
                assert phrase not in low, f"prediction-like language in: {title}"
        assert all(c["version"] for c in as_chunks())

    def test_knowledge_is_searchable(self):
        from cryptobot.ai.knowledge import KnowledgeBase

        kb = KnowledgeBase()
        kb.load()
        for query in ["what is RSI", "slippage", "maker taker fees", "leverage",
                      "position sizing"]:
            assert kb.search(query)["results"], f"no KB hit for {query}"