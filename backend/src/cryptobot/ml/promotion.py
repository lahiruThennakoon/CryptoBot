"""Champion/challenger promotion gates.

A challenger is promoted only when ALL criteria pass. Absent a champion, the
challenger must still clear the absolute gates — there is no free promotion.
A model is never promoted on the basis of the bot's own recent live results.
"""

from __future__ import annotations

from dataclasses import dataclass

from cryptobot.ml.evaluate import EvalResult


@dataclass(frozen=True)
class PromotionCriteria:
    min_val_auc: float = 0.53                # must beat coin-flip with margin on validation
    min_auc_improvement: float = 0.01        # vs champion's validation AUC
    min_test_expectancy: float = 0.0         # after costs, on the untouched test period
    min_test_signals: int = 30               # enough test signals to mean anything
    max_test_brier: float = 0.26             # calibration sanity


@dataclass(frozen=True)
class PromotionDecision:
    promote: bool
    reasons: tuple[str, ...]

    @property
    def summary(self) -> str:
        verdict = "PROMOTE" if self.promote else "REJECT"
        return f"{verdict}: " + "; ".join(self.reasons)


def decide_promotion(
    challenger_val: EvalResult,
    challenger_test: EvalResult,
    champion_val: EvalResult | None = None,
    criteria: PromotionCriteria | None = None,
) -> PromotionDecision:
    c = criteria or PromotionCriteria()
    reasons: list[str] = []
    ok = True

    if challenger_val.auc < c.min_val_auc:
        ok = False
        reasons.append(f"val AUC {challenger_val.auc:.3f} < {c.min_val_auc}")
    else:
        reasons.append(f"val AUC {challenger_val.auc:.3f} ok")

    if champion_val is not None:
        needed = champion_val.auc + c.min_auc_improvement
        if challenger_val.auc < needed:
            ok = False
            reasons.append(
                f"does not beat champion (needs {needed:.3f}, has {challenger_val.auc:.3f})"
            )
        else:
            reasons.append(f"beats champion val AUC {champion_val.auc:.3f}")

    if challenger_test.n_signals < c.min_test_signals:
        ok = False
        reasons.append(f"only {challenger_test.n_signals} test signals (< {c.min_test_signals})")
    elif (
        challenger_test.expectancy_after_costs is None
        or challenger_test.expectancy_after_costs <= c.min_test_expectancy
    ):
        ok = False
        reasons.append(
            f"test expectancy after costs {challenger_test.expectancy_after_costs} not > "
            f"{c.min_test_expectancy}"
        )
    else:
        reasons.append(
            f"test expectancy {challenger_test.expectancy_after_costs:.5f} over "
            f"{challenger_test.n_signals} signals"
        )

    if challenger_test.brier > c.max_test_brier:
        ok = False
        reasons.append(f"test Brier {challenger_test.brier:.3f} > {c.max_test_brier}")

    return PromotionDecision(promote=ok, reasons=tuple(reasons))
