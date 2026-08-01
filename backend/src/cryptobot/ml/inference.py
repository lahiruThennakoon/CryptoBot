"""Runtime inference for deployed ML models (optional).

Loads the champion from the file registry and scores the latest bar.
Absent registry or deployed model → returns None (scorer ML weight stays zero).
"""

from __future__ import annotations

from collections.abc import Sequence

from cryptobot.core.logging import get_logger
from cryptobot.ml.features import FeatureBuilder, FeatureSpec
from cryptobot.ml.registry import ModelRegistry
from cryptobot.strategies.base import BarLike

logger = get_logger(__name__)

DEFAULT_MODEL_NAME = "direction_1h"


class DeployedModelPredictor:
    """Lazy-loaded predictor for the deployed champion model."""

    def __init__(self, registry_dir: str, model_name: str = DEFAULT_MODEL_NAME) -> None:
        self._registry = ModelRegistry(registry_dir)
        self._model_name = model_name
        self._record_id: str | None = None
        self._model: object | None = None
        self._builder = FeatureBuilder(FeatureSpec())

    def _ensure_loaded(self) -> bool:
        record = self._registry.deployed(self._model_name)
        if record is None:
            return False
        if self._record_id != record.id:
            self._model = self._registry.load_model(record.id)
            self._record_id = record.id
            logger.info("ml_model_loaded", model=record.name, version=record.version,
                        algorithm=record.algorithm)
        return self._model is not None

    def probability_up(
        self,
        bars: Sequence[BarLike],
        btc_closes: Sequence[float] | None = None,
    ) -> float | None:
        if not self._ensure_loaded() or self._model is None:
            return None
        row = self._builder.inference_row(bars, btc_closes=btc_closes)
        if row is None:
            return None
        proba = self._model.predict_proba([row])  # type: ignore[attr-defined]
        return float(proba[0])
