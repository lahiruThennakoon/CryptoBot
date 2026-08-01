"""Every machine reason code must have a human explanation; verdicts must be honest."""

from cryptobot.analytics.explanations import EXPLANATIONS, explain, summarize_no_trades
from cryptobot.analytics.verdicts import judge
from cryptobot.backtest.metrics import Report


class TestExplanationsCoverage:
    def test_all_risk_engine_codes_covered(self):
        risk_codes = [
            "HALTED", "DAILY_LOSS_LIMIT", "MAX_DRAWDOWN", "CONSECUTIVE_LOSSES",
            "MAX_TRADES_PER_DAY", "MAX_POSITIONS", "LOW_CONFIDENCE", "NO_STOP",
            "INVALID_STOP", "STOP_TOO_TIGHT", "MAX_EXPOSURE",
            "SIZE_BELOW_MIN_QTY", "SIZE_BELOW_MIN_NOTIONAL",
        ]
        for code in risk_codes:
            assert code in EXPLANATIONS, f"no plain-language entry for {code}"

    def test_all_runtime_codes_covered(self):
        for code in ["COOLDOWN", "REGIME_EXCLUDED", "COST_GATE", "STALE_DATA",
                     "INSUFFICIENT_CASH"]:
            assert code in EXPLANATIONS, f"no plain-language entry for {code}"

    def test_explanations_avoid_jargon(self):
        import re

        banned = ["atr", "sma", "rsi", "notional", "regime_", "quantile"]
        for exp in EXPLANATIONS.values():
            lower = exp.text.lower()
            for word in banned:
                assert not re.search(rf"\b{re.escape(word)}\b", lower), (
                    f"jargon '{word}' in: {exp.title}"
                )

    def test_unknown_code_degrades_gracefully(self):
        assert explain("SOME_FUTURE_CODE").title
        assert explain(None).title

    def test_summary_counts_and_tone(self):
        s = summarize_no_trades({"COST_GATE": 3, "REGIME_EXCLUDED": 5})
        assert "8" in s
        assert "not a malfunction" in s
        assert summarize_no_trades({})  # empty period also gets a real sentence


def report(**kw) -> Report:
    r = Report()
    for k, v in kw.items():
        setattr(r, k, v)
    return r


class TestVerdicts:
    def test_no_trades(self):
        v = judge(report(n_trades=0))
        assert v.grade == "no_trades"

    def test_small_sample_is_inconclusive_even_if_profitable(self):
        v = judge(report(n_trades=5, net_return_pct=40.0, beat_buy_hold=True))
        assert v.grade == "inconclusive"   # luck-sized samples never get praise

    def test_losses_are_no_edge(self):
        v = judge(report(n_trades=50, net_return_pct=-2.0))
        assert v.grade == "no_edge"
        assert "does not deserve real money" in v.detail

    def test_profit_below_buy_hold_is_weak(self):
        v = judge(report(n_trades=50, net_return_pct=5.0,
                         buy_hold_return_pct=20.0, beat_buy_hold=False))
        assert v.grade == "weak"
        assert "holding" in v.headline

    def test_promising_still_hedged(self):
        v = judge(report(n_trades=50, net_return_pct=15.0,
                         buy_hold_return_pct=10.0, beat_buy_hold=True))
        assert v.grade == "promising"
        assert "guarantees nothing" in v.detail