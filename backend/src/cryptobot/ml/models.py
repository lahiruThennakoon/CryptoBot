"""Model zoo.

PureLogisticRegression is the dependency-free baseline that is ALWAYS
available — every other model must beat it to matter. sklearn-backed models
(gradient boosting, random forest) load lazily and require the [ml] extra.
All models are seeded for reproducibility.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Protocol


class BinaryClassifier(Protocol):
    name: str
    seed: int

    def fit(self, x: list[list[float]], y: list[int]) -> None: ...
    def predict_proba(self, x: list[list[float]]) -> list[float]: ...


@dataclass
class PureLogisticRegression:
    """L2-regularized logistic regression via gradient descent. Stdlib only."""

    name: str = "logistic_regression"
    seed: int = 42
    learning_rate: float = 0.1
    epochs: int = 300
    l2: float = 1e-3
    _weights: list[float] = field(default_factory=list)
    _bias: float = 0.0
    _means: list[float] = field(default_factory=list)
    _stds: list[float] = field(default_factory=list)

    def _standardize(self, x: list[list[float]]) -> list[list[float]]:
        return [
            [(row[j] - self._means[j]) / self._stds[j] for j in range(len(row))]
            for row in x
        ]

    def fit(self, x: list[list[float]], y: list[int]) -> None:
        if not x:
            raise ValueError("empty training set")
        n, d = len(x), len(x[0])
        self._means = [sum(row[j] for row in x) / n for j in range(d)]
        self._stds = [
            math.sqrt(sum((row[j] - self._means[j]) ** 2 for row in x) / n) or 1.0
            for j in range(d)
        ]
        xs = self._standardize(x)
        rng = random.Random(self.seed)
        self._weights = [rng.gauss(0, 0.01) for _ in range(d)]
        self._bias = 0.0
        for _ in range(self.epochs):
            grad_w = [0.0] * d
            grad_b = 0.0
            for row, label in zip(xs, y, strict=True):
                p = self._sigmoid(sum(w * v for w, v in zip(self._weights, row, strict=True)) + self._bias)
                err = p - label
                for j in range(d):
                    grad_w[j] += err * row[j]
                grad_b += err
            for j in range(d):
                self._weights[j] -= self.learning_rate * (grad_w[j] / n + self.l2 * self._weights[j])
            self._bias -= self.learning_rate * grad_b / n

    def predict_proba(self, x: list[list[float]]) -> list[float]:
        xs = self._standardize(x)
        return [
            self._sigmoid(sum(w * v for w, v in zip(self._weights, row, strict=True)) + self._bias)
            for row in xs
        ]

    @staticmethod
    def _sigmoid(z: float) -> float:
        if z < -35:
            return 1e-15
        if z > 35:
            return 1 - 1e-15
        return 1.0 / (1.0 + math.exp(-z))


@dataclass
class SklearnModel:
    """Lazy wrapper for sklearn classifiers (requires `pip install -e .[ml]`)."""

    algorithm: str          # "gbdt" | "random_forest"
    name: str = ""
    seed: int = 42
    _model: object = None

    def __post_init__(self) -> None:
        self.name = self.name or self.algorithm

    def _build(self) -> object:
        try:
            from sklearn.ensemble import (
                GradientBoostingClassifier,
                RandomForestClassifier,
            )
        except ImportError as exc:
            raise RuntimeError(
                "scikit-learn not installed — run: pip install -e '.[ml]'"
            ) from exc
        if self.algorithm == "gbdt":
            return GradientBoostingClassifier(random_state=self.seed, max_depth=3,
                                              n_estimators=200, learning_rate=0.05)
        if self.algorithm == "random_forest":
            return RandomForestClassifier(random_state=self.seed, n_estimators=300,
                                          max_depth=6, min_samples_leaf=20, n_jobs=-1)
        raise ValueError(f"unknown algorithm {self.algorithm}")

    def fit(self, x: list[list[float]], y: list[int]) -> None:
        self._model = self._build()
        self._model.fit(x, y)  # type: ignore[attr-defined]

    def predict_proba(self, x: list[list[float]]) -> list[float]:
        assert self._model is not None, "fit() first"
        return [float(p[1]) for p in self._model.predict_proba(x)]  # type: ignore[attr-defined]


def model_zoo(seed: int = 42) -> dict[str, BinaryClassifier]:
    """All candidate models. The pure-python baseline is always present."""
    return {
        "logistic_regression": PureLogisticRegression(seed=seed),
        "gbdt": SklearnModel("gbdt", seed=seed),
        "random_forest": SklearnModel("random_forest", seed=seed),
    }
