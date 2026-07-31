"""Feature/prediction drift monitoring via Population Stability Index.

PSI conventions: < 0.1 stable · 0.1–0.25 moderate shift · > 0.25 severe.
A deployed model whose inputs drift severely should be demoted to the
rule-based baselines until retrained and re-validated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

PSI_MODERATE = 0.10
PSI_SEVERE = 0.25
_EPS = 1e-6


def make_reference(values: list[float], n_bins: int = 10) -> list[float]:
    """Store decile edges of the training distribution for later comparison."""
    if len(values) < n_bins:
        raise ValueError("not enough values for reference distribution")
    ordered = sorted(values)
    return [ordered[int(len(ordered) * k / n_bins)] for k in range(1, n_bins)]


def psi(reference_edges: list[float], current: list[float]) -> float:
    if not current:
        raise ValueError("no current values")
    n_bins = len(reference_edges) + 1
    expected = 1.0 / n_bins                       # by construction of decile edges

    counts = [0] * n_bins
    for v in current:
        bin_i = 0
        while bin_i < len(reference_edges) and v > reference_edges[bin_i]:
            bin_i += 1
        counts[bin_i] += 1
    total = len(current)

    value = 0.0
    for c in counts:
        actual = max(c / total, _EPS)
        exp = max(expected, _EPS)
        value += (actual - exp) * math.log(actual / exp)
    return value


@dataclass(frozen=True)
class DriftReport:
    per_feature: dict[str, float]
    worst_feature: str
    worst_psi: float

    @property
    def severe(self) -> bool:
        return self.worst_psi > PSI_SEVERE

    @property
    def moderate(self) -> bool:
        return self.worst_psi > PSI_MODERATE

    def summary(self) -> str:
        level = "SEVERE" if self.severe else "moderate" if self.moderate else "stable"
        return f"drift={level} worst={self.worst_feature} psi={self.worst_psi:.3f}"


def check_drift(
    reference: dict[str, list[float]],       # feature name → decile edges
    current_rows: list[list[float]],
    feature_names: list[str],
) -> DriftReport:
    per_feature: dict[str, float] = {}
    for j, name in enumerate(feature_names):
        edges = reference.get(name)
        if edges is None:
            continue
        per_feature[name] = psi(edges, [row[j] for row in current_rows])
    if not per_feature:
        raise ValueError("no overlapping features between reference and current")
    worst = max(per_feature, key=lambda k: per_feature[k])
    return DriftReport(per_feature=per_feature, worst_feature=worst,
                       worst_psi=per_feature[worst])
