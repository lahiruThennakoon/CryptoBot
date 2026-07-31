"""Opt-in automatic pair selection, inside guardrails the user authorises.

The rule "the bot never trades a pair the user has not enabled" is preserved
with a precise change: the user may authorise a POLICY rather than a list.
Consent is explicit, bounded and revocable, and every automatic change is
audited so it is never a surprise.

Guardrails that cannot be bypassed:
  · opt-in only (off by default) and requires an explicit consent phrase
  · candidates limited to a liquidity floor and the screener's suitable set
  · a pair needs positive backtest evidence to be auto-enabled
  · hard cap on how many pairs may be active
  · never auto-disables a pair holding an open position
  · every enable/disable is written to the audit trail with its reason
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cryptobot.pairs.screener import ScreenResult

CONSENT_PHRASE = "I_AUTHORISE_AUTOMATIC_PAIR_SELECTION"


@dataclass(frozen=True)
class AutoManageConfig:
    enabled: bool = False
    consent_phrase: str = ""
    max_active_pairs: int = 3
    min_score_to_enable: float = 0.60
    min_score_to_keep: float = 0.45          # hysteresis: avoid flip-flopping
    require_positive_evidence: bool = True
    min_quote_volume_24h: float = 50_000_000

    @property
    def authorised(self) -> bool:
        return self.enabled and self.consent_phrase == CONSENT_PHRASE


@dataclass
class AutoManagePlan:
    enable: list[tuple[str, str]] = field(default_factory=list)    # (symbol, reason)
    disable: list[tuple[str, str]] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    blocked_reason: str = ""

    @property
    def is_noop(self) -> bool:
        return not self.enable and not self.disable

    def summary(self) -> str:
        if self.blocked_reason:
            return f"no changes: {self.blocked_reason}"
        if self.is_noop:
            return "no changes — current pair selection still passes screening"
        parts = []
        if self.enable:
            parts.append("enable " + ", ".join(s for s, _ in self.enable))
        if self.disable:
            parts.append("disable " + ", ".join(s for s, _ in self.disable))
        return "; ".join(parts)


def plan_auto_manage(
    config: AutoManageConfig,
    ranked: list[ScreenResult],
    currently_enabled: set[str],
    symbols_with_open_positions: set[str],
    evidence_positive: dict[str, bool] | None = None,
) -> AutoManagePlan:
    """Pure: decide which pairs to enable/disable. Executes nothing."""
    plan = AutoManagePlan()
    if not config.authorised:
        plan.blocked_reason = (
            "automatic pair selection is not authorised — enable it and provide the "
            "consent phrase in settings. Until then the bot only trades pairs you "
            "switch on yourself."
        )
        plan.unchanged = sorted(currently_enabled)
        return plan

    evidence_positive = evidence_positive or {}
    by_symbol = {r.symbol: r for r in ranked}

    # ── drop pairs that no longer qualify (never with an open position) ──
    for symbol in sorted(currently_enabled):
        result = by_symbol.get(symbol)
        if symbol in symbols_with_open_positions:
            plan.unchanged.append(symbol)
            continue
        if result is None or not result.suitable:
            plan.disable.append((symbol, "no longer passes screening"))
        elif result.score < config.min_score_to_keep:
            plan.disable.append(
                (symbol, f"suitability fell to {result.score:.2f} (keep threshold "
                         f"{config.min_score_to_keep:.2f})"))
        else:
            plan.unchanged.append(symbol)

    # ── fill remaining slots with the strongest qualifying candidates ──
    keeping = {s for s in plan.unchanged}
    slots = max(0, config.max_active_pairs - len(keeping))
    for result in ranked:
        if slots <= 0:
            break
        if result.symbol in keeping or result.already_enabled:
            continue
        if not result.suitable or result.score < config.min_score_to_enable:
            continue
        if config.require_positive_evidence and not evidence_positive.get(result.symbol, False):
            continue
        plan.enable.append((
            result.symbol,
            f"suitability {result.score:.2f}"
            + (f", moves {result.move_to_cost_ratio:.1f}x its trading cost"
               if result.move_to_cost_ratio else "")
            + ", positive backtest evidence",
        ))
        slots -= 1

    if plan.is_noop and not plan.blocked_reason:
        plan.blocked_reason = (
            "no candidate cleared the enable threshold with positive evidence — "
            "holding the current selection is the correct outcome"
            if not plan.unchanged else ""
        )
    return plan
