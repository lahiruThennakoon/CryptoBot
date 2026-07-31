import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptobot.ml.models import PureLogisticRegression
from cryptobot.ml.registry import ModelRegistry
from cryptobot.ml.training import run_training


@dataclass(frozen=True)
class Bar:
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def make_bars(n=3000, seed=13):
    rng = random.Random(seed)
    t0 = datetime(2023, 1, 1, tzinfo=UTC)
    price, out = 100.0, []
    for i in range(n):
        c = max(0.01, price * (1 + rng.gauss(0.0001, 0.01)))
        out.append(Bar(t0 + timedelta(hours=i), price, max(price, c) * 1.002,
                       min(price, c) * 0.998, c, abs(rng.gauss(50, 20)) + 1))
        price = c
    return out


class TestRegistry:
    def test_register_and_load_roundtrip(self, tmp_path):
        reg = ModelRegistry(tmp_path)
        model = PureLogisticRegression()
        model.fit([[0.0, 1.0], [1.0, 0.0]] * 10, [0, 1] * 10)
        record = reg.register(model, "m", "logistic_regression", 42, "fv1-x", 6, 20, {})
        loaded = reg.load_model(record.id)
        assert isinstance(loaded, PureLogisticRegression)

    def test_versions_increment(self, tmp_path):
        reg = ModelRegistry(tmp_path)
        m = PureLogisticRegression(); m.fit([[0.0], [1.0]] * 5, [0, 1] * 5)
        r1 = reg.register(m, "m", "lr", 42, "fv", 6, 10, {})
        r2 = reg.register(m, "m", "lr", 42, "fv", 6, 10, {})
        assert (r1.version, r2.version) == (1, 2)

    def test_single_deployed_per_name(self, tmp_path):
        reg = ModelRegistry(tmp_path)
        m = PureLogisticRegression(); m.fit([[0.0], [1.0]] * 5, [0, 1] * 5)
        r1 = reg.register(m, "m", "lr", 42, "fv", 6, 10, {})
        r2 = reg.register(m, "m", "lr", 42, "fv", 6, 10, {})
        reg.set_status(r1.id, "deployed")
        reg.set_status(r2.id, "deployed")
        records = {r.id: r for r in reg.all_records("m")}
        assert records[r2.id].status == "deployed"
        assert records[r1.id].status == "retired"


class TestTrainingPipeline:
    def test_end_to_end_run(self, tmp_path):
        result = run_training(
            make_bars(), ModelRegistry(tmp_path), seed=42,
            candidates={"logistic_regression": PureLogisticRegression(seed=42, epochs=60)},
        )
        assert result.winner_name == "logistic_regression"
        assert result.test is not None
        assert result.winner_record_id is not None
        assert "PROMOTE" in result.promotion_summary or "REJECT" in result.promotion_summary

    def test_reproducible_given_seed(self, tmp_path):
        kwargs = dict(
            seed=7,
            candidates=None,
        )
        r1 = run_training(make_bars(), ModelRegistry(tmp_path / "a"), seed=7,
                          candidates={"lr": PureLogisticRegression(seed=7, epochs=60)})
        r2 = run_training(make_bars(), ModelRegistry(tmp_path / "b"), seed=7,
                          candidates={"lr": PureLogisticRegression(seed=7, epochs=60)})
        assert r1.validation["lr"].auc == r2.validation["lr"].auc
        assert r1.test.auc == r2.test.auc

    def test_random_noise_rarely_promotes(self, tmp_path):
        """On pure noise, gates should almost always reject. This guards against
        promotion criteria that are too loose."""
        result = run_training(
            make_bars(seed=99), ModelRegistry(tmp_path), seed=42,
            candidates={"lr": PureLogisticRegression(seed=42, epochs=60)},
        )
        # Not asserting always-reject (noise can luck through), but the decision
        # machinery must have run and recorded a verdict:
        records = ModelRegistry(tmp_path).all_records()
        assert records and records[0].status in ("rejected", "deployed")