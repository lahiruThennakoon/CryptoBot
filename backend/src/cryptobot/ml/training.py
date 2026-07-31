"""End-to-end training pipeline: features → embargoed splits → candidates →
validation selection → untouched-test evaluation → registry → promotion gate.

The test segment is evaluated exactly once, for the model that won on
validation. Nothing about the test result feeds back into selection.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from cryptobot.core.logging import get_logger
from cryptobot.costs.model import CostModel
from cryptobot.ml.drift import make_reference
from cryptobot.ml.evaluate import EvalResult, evaluate
from cryptobot.ml.features import FeatureBuilder, FeatureSpec
from cryptobot.ml.models import BinaryClassifier, model_zoo
from cryptobot.ml.promotion import PromotionCriteria, decide_promotion
from cryptobot.ml.registry import ModelRegistry
from cryptobot.ml.splits import chronological_split
from cryptobot.strategies.base import BarLike

logger = get_logger(__name__)


@dataclass
class TrainingResult:
    winner_name: str
    winner_record_id: str | None
    validation: dict[str, EvalResult] = field(default_factory=dict)
    test: EvalResult | None = None
    promotion_summary: str = ""
    promoted: bool = False


def run_training(
    bars: Sequence[BarLike],
    registry: ModelRegistry,
    model_name: str = "direction_1h",
    horizon: int = 6,
    seed: int = 42,
    threshold: float = 0.6,
    feature_spec: FeatureSpec | None = None,
    costs: CostModel | None = None,
    candidates: dict[str, BinaryClassifier] | None = None,
    criteria: PromotionCriteria | None = None,
    btc_closes: Sequence[float] | None = None,
) -> TrainingResult:
    costs = costs or CostModel()
    builder = FeatureBuilder(feature_spec)
    matrix = builder.build(bars, btc_closes=btc_closes, horizon=horizon,
                           label_cost_threshold=costs.round_trip_fraction)
    if len(matrix.rows) < 500:
        raise ValueError(f"only {len(matrix.rows)} usable rows — insufficient data to train")

    closes = [float(b.close) for b in bars]  # type: ignore[arg-type]
    forward_returns = [
        closes[i + horizon] / closes[i] - 1 for i in matrix.bar_indices
    ]

    split = chronological_split(len(matrix.rows), embargo=horizon * 2)
    x_train = [matrix.rows[i] for i in split.train]
    y_train = [matrix.labels[i] for i in split.train]
    x_val = [matrix.rows[i] for i in split.validation]
    y_val = [matrix.labels[i] for i in split.validation]
    fwd_val = [forward_returns[i] for i in split.validation]
    x_test = [matrix.rows[i] for i in split.test]
    y_test = [matrix.labels[i] for i in split.test]
    fwd_test = [forward_returns[i] for i in split.test]

    result = TrainingResult(winner_name="", winner_record_id=None)
    trained: dict[str, BinaryClassifier] = {}
    for name, model in (candidates or model_zoo(seed)).items():
        try:
            model.fit(x_train, y_train)
        except RuntimeError as exc:  # optional dependency missing → skip, keep baseline
            logger.warning("candidate_skipped", model=name, reason=str(exc))
            continue
        trained[name] = model
        result.validation[name] = evaluate(
            y_val, model.predict_proba(x_val), fwd_val, threshold, costs
        )
        logger.info("candidate_validated", model=name,
                    auc=round(result.validation[name].auc, 4),
                    expectancy=result.validation[name].expectancy_after_costs)

    if not trained:
        raise RuntimeError("no candidate could be trained")

    # select on VALIDATION only (never test)
    winner = max(result.validation, key=lambda k: result.validation[k].auc)
    result.winner_name = winner

    # single untouched-test evaluation for the winner
    result.test = evaluate(
        y_test, trained[winner].predict_proba(x_test), fwd_test, threshold, costs
    )

    reference = {
        name: make_reference([row[j] for row in x_train])
        for j, name in enumerate(matrix.names)
    }
    record = registry.register(
        model=trained[winner], name=model_name, algorithm=winner, seed=seed,
        features_version=matrix.version, horizon=horizon, train_rows=len(x_train),
        metrics={
            "validation": result.validation[winner].__dict__,
            "test": result.test.__dict__,
            "threshold": threshold,
        },
        reference_distribution=reference,
    )
    result.winner_record_id = record.id

    champion = registry.deployed(model_name, matrix.version)
    champion_val = None
    if champion is not None and "validation" in champion.metrics:
        champion_val = EvalResult(**champion.metrics["validation"])
    decision = decide_promotion(result.validation[winner], result.test,
                                champion_val, criteria)
    result.promotion_summary = decision.summary
    result.promoted = decision.promote
    registry.set_status(
        record.id,
        "deployed" if decision.promote else "rejected",
        note=decision.summary,
    )
    logger.info("training_complete", winner=winner, promoted=decision.promote,
                decision=decision.summary)
    return result
