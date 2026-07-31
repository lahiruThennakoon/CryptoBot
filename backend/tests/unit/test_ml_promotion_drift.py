import random

import pytest

from cryptobot.ml.drift import check_drift, make_reference, psi
from cryptobot.ml.evaluate import EvalResult
from cryptobot.ml.promotion import PromotionCriteria, decide_promotion


def eval_result(auc=0.60, expectancy=0.002, n_signals=100, brier=0.22) -> EvalResult:
    return EvalResult(
        n_samples=1000, auc=auc, brier=brier, accuracy=0.6, precision=0.6,
        recall=0.5, base_rate=0.45, threshold=0.6, n_signals=n_signals,
        expectancy_after_costs=expectancy, hit_rate=0.55,
    )


class TestPromotionGates:
    def test_good_challenger_promotes(self):
        d = decide_promotion(eval_result(), eval_result())
        assert d.promote, d.summary

    def test_weak_val_auc_rejected(self):
        d = decide_promotion(eval_result(auc=0.51), eval_result())
        assert not d.promote

    def test_negative_test_expectancy_rejected(self):
        d = decide_promotion(eval_result(), eval_result(expectancy=-0.001))
        assert not d.promote

    def test_too_few_test_signals_rejected(self):
        d = decide_promotion(eval_result(), eval_result(n_signals=5))
        assert not d.promote

    def test_must_beat_champion_by_margin(self):
        champion = eval_result(auc=0.62)
        challenger_equal = eval_result(auc=0.62)
        assert not decide_promotion(challenger_equal, eval_result(), champion).promote
        challenger_better = eval_result(auc=0.64)
        assert decide_promotion(challenger_better, eval_result(), champion).promote

    def test_poor_calibration_rejected(self):
        d = decide_promotion(eval_result(), eval_result(brier=0.40),
                             criteria=PromotionCriteria())
        assert not d.promote


class TestDrift:
    def test_identical_distribution_is_stable(self):
        rng = random.Random(3)
        ref_values = [rng.gauss(0, 1) for _ in range(2000)]
        edges = make_reference(ref_values)
        current = [rng.gauss(0, 1) for _ in range(1000)]
        assert psi(edges, current) < 0.1

    def test_shifted_distribution_detected(self):
        rng = random.Random(3)
        edges = make_reference([rng.gauss(0, 1) for _ in range(2000)])
        shifted = [rng.gauss(2.5, 1) for _ in range(1000)]
        assert psi(edges, shifted) > 0.25

    def test_check_drift_reports_worst_feature(self):
        rng = random.Random(5)
        reference = {
            "stable_feat": make_reference([rng.gauss(0, 1) for _ in range(2000)]),
            "drifted_feat": make_reference([rng.gauss(0, 1) for _ in range(2000)]),
        }
        rows = [[rng.gauss(0, 1), rng.gauss(3, 1)] for _ in range(500)]
        report = check_drift(reference, rows, ["stable_feat", "drifted_feat"])
        assert report.worst_feature == "drifted_feat"
        assert report.severe

    def test_empty_current_raises(self):
        with pytest.raises(ValueError):
            psi([0.0, 1.0], [])