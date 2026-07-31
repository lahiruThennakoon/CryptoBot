import random

from cryptobot.costs.model import CostModel
from cryptobot.ml.evaluate import auc_score, evaluate
from cryptobot.ml.models import PureLogisticRegression


def separable_data(n=400, seed=1):
    rng = random.Random(seed)
    x, y = [], []
    for _ in range(n):
        label = rng.randint(0, 1)
        x.append([rng.gauss(2.0 if label else -2.0, 1.0), rng.gauss(0, 1)])
        y.append(label)
    return x, y


class TestPureLogisticRegression:
    def test_learns_separable_data(self):
        x, y = separable_data()
        model = PureLogisticRegression(seed=42)
        model.fit(x, y)
        probs = model.predict_proba(x)
        assert auc_score(y, probs) > 0.95

    def test_deterministic_given_seed(self):
        x, y = separable_data()
        a = PureLogisticRegression(seed=7); a.fit(x, y)
        b = PureLogisticRegression(seed=7); b.fit(x, y)
        assert a.predict_proba(x[:20]) == b.predict_proba(x[:20])

    def test_probabilities_bounded(self):
        x, y = separable_data()
        model = PureLogisticRegression()
        model.fit(x, y)
        assert all(0.0 < p < 1.0 for p in model.predict_proba(x))


class TestMetrics:
    def test_auc_perfect_and_random(self):
        y = [0, 0, 1, 1]
        assert auc_score(y, [0.1, 0.2, 0.8, 0.9]) == 1.0
        assert auc_score(y, [0.9, 0.8, 0.2, 0.1]) == 0.0
        assert auc_score(y, [0.5, 0.5, 0.5, 0.5]) == 0.5

    def test_evaluate_economic_view(self):
        y = [1, 1, 0, 0]
        probs = [0.9, 0.8, 0.7, 0.1]      # 3 signals at threshold 0.6
        fwd = [0.02, 0.03, -0.02, 0.0]
        r = evaluate(y, probs, fwd, threshold=0.6,
                     costs=CostModel(taker_fee=0.001, half_spread=0.0003,
                                     slippage=0.0005, latency_drift=0.0002))
        assert r.n_signals == 3
        assert r.expectancy_after_costs is not None
        expected = (0.02 + 0.03 - 0.02) / 3 - 2 * (0.001 + 0.0003 + 0.0005 + 0.0002)
        assert abs(r.expectancy_after_costs - expected) < 1e-9

    def test_evaluate_no_signals(self):
        r = evaluate([1, 0], [0.1, 0.1], [0.01, 0.01], threshold=0.6)
        assert r.n_signals == 0 and r.expectancy_after_costs is None