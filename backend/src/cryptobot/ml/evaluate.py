"""Model evaluation: statistical metrics AND economic value after costs.

A model with great AUC and negative expectancy after costs is worthless for
trading; both views are computed and promotion gates require both.
"""

from __future__ import annotations

from dataclasses import dataclass

from cryptobot.costs.model import CostModel


@dataclass(frozen=True)
class EvalResult:
    n_samples: int
    auc: float
    brier: float
    accuracy: float
    precision: float | None
    recall: float | None
    base_rate: float
    # economic view at the given threshold:
    threshold: float
    n_signals: int
    expectancy_after_costs: float | None    # mean forward return net of costs per signal
    hit_rate: float | None


def auc_score(y_true: list[int], y_prob: list[float]) -> float:
    """Rank-based AUC (Mann-Whitney), stdlib only."""
    pairs = sorted(zip(y_prob, y_true, strict=True))
    ranks: dict[int, float] = {}
    i = 0
    rank_sum_pos = 0.0
    n_pos = sum(y_true)
    n_neg = len(y_true) - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5
    while i < len(pairs):
        j = i
        while j < len(pairs) and pairs[j][0] == pairs[i][0]:
            j += 1
        avg_rank = (i + j + 1) / 2  # 1-based average rank for ties
        for k in range(i, j):
            if pairs[k][1] == 1:
                rank_sum_pos += avg_rank
        i = j
    return (rank_sum_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def evaluate(
    y_true: list[int],
    y_prob: list[float],
    forward_returns: list[float] | None = None,
    threshold: float = 0.6,
    costs: CostModel | None = None,
) -> EvalResult:
    n = len(y_true)
    if n == 0 or n != len(y_prob):
        raise ValueError("empty or mismatched evaluation inputs")
    costs = costs or CostModel()

    predictions = [1 if p >= threshold else 0 for p in y_prob]
    tp = sum(1 for t, p in zip(y_true, predictions, strict=True) if t == 1 and p == 1)
    fp = sum(1 for t, p in zip(y_true, predictions, strict=True) if t == 0 and p == 1)
    fn = sum(1 for t, p in zip(y_true, predictions, strict=True) if t == 1 and p == 0)
    correct = sum(1 for t, p in zip(y_true, predictions, strict=True) if t == p)

    expectancy = hit_rate = None
    n_signals = tp + fp
    if forward_returns is not None and n_signals > 0:
        selected = [
            forward_returns[i] for i in range(n) if predictions[i] == 1
        ]
        net = [r - costs.round_trip_fraction for r in selected]
        expectancy = sum(net) / len(net)
        hit_rate = sum(1 for r in net if r > 0) / len(net)

    return EvalResult(
        n_samples=n,
        auc=auc_score(y_true, y_prob),
        brier=sum((p - t) ** 2 for p, t in zip(y_prob, y_true, strict=True)) / n,
        accuracy=correct / n,
        precision=tp / (tp + fp) if (tp + fp) > 0 else None,
        recall=tp / (tp + fn) if (tp + fn) > 0 else None,
        base_rate=sum(y_true) / n,
        threshold=threshold,
        n_signals=n_signals,
        expectancy_after_costs=expectancy,
        hit_rate=hit_rate,
    )
