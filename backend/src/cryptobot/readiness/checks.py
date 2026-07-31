"""Live-readiness evaluation — pure logic over gathered facts.

The checker can only ever conclude NOT READY or READY FOR OWNER REVIEW.
It has no ability to enable live trading; that remains a multi-step manual
gate (docs/risk-policy.md §9). MANUAL items must be verified and signed off
by the owner in docs/live-readiness/approval.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Status(str, Enum):
    PASS = "PASS"        # noqa: S105 — check status, not a password
    FAIL = "FAIL"
    WARN = "WARN"
    MANUAL = "MANUAL"    # cannot be automated; requires owner verification


@dataclass(frozen=True)
class CheckResult:
    category: str        # security | reliability | performance | gate
    name: str
    status: Status
    detail: str = ""


@dataclass
class Facts:
    """Everything the evaluator needs, gathered by service.py (or tests)."""

    mode: str = "paper"
    api_secret_is_default: bool = True
    gitignore_covers_env: bool = False
    env_example_has_secrets: bool = False
    testnet_keys_configured: bool = False
    live_keys_configured: bool = False
    confirm_phrase_set: bool = False
    # evidence from the database (None = unavailable)
    paper_trading_days: int | None = None
    closed_paper_trades: int | None = None
    paper_net_pnl: float | None = None
    max_drawdown_pct: float | None = None
    db_reachable: bool = False
    redis_reachable: bool = False
    deployed_model: str | None = None
    # graduation thresholds (docs/prd.md §3)
    required_paper_days: int = 90
    required_trades: int = 100
    max_allowed_drawdown_pct: float = 15.0
    manual_drills: dict[str, bool] = field(default_factory=dict)  # name → acked


DRILLS = (
    "restart_and_reconciliation",
    "api_disconnection",
    "duplicate_order_prevention",
    "emergency_stop",
    "backup_restore",
    "key_rotation",
)


def evaluate(facts: Facts) -> list[CheckResult]:
    out: list[CheckResult] = []
    add = out.append

    # ── security ─────────────────────────────────────────────────────
    add(CheckResult("security", "live trading disabled",
        Status.PASS if facts.mode != "live" else Status.FAIL,
        f"mode={facts.mode}"))
    add(CheckResult("security", "live gate factors absent until approval",
        Status.PASS if not (facts.live_keys_configured or facts.confirm_phrase_set)
        else Status.WARN,
        "live credentials/confirmation must only be set after owner sign-off"))
    add(CheckResult("security", "API_SECRET_KEY configured",
        Status.FAIL if facts.api_secret_is_default else Status.PASS,
        "dashboard auth fails closed on default key" if facts.api_secret_is_default else ""))
    add(CheckResult("security", ".env excluded from git",
        Status.PASS if facts.gitignore_covers_env else Status.FAIL))
    add(CheckResult("security", ".env.example contains placeholders only",
        Status.FAIL if facts.env_example_has_secrets else Status.PASS))
    add(CheckResult("security", "secret-scan (gitleaks) in pre-commit and CI",
        Status.MANUAL, "verify hooks installed: pre-commit install"))
    add(CheckResult("security", "live API key: withdrawals disabled + IP allowlist",
        Status.MANUAL, "verify in Binance key settings before any live enablement"))

    # ── reliability ──────────────────────────────────────────────────
    add(CheckResult("reliability", "database reachable",
        Status.PASS if facts.db_reachable else Status.FAIL))
    add(CheckResult("reliability", "redis reachable",
        Status.PASS if facts.redis_reachable else Status.FAIL))
    add(CheckResult("reliability", "testnet credentials configured",
        Status.PASS if facts.testnet_keys_configured else Status.WARN,
        "needed for testnet E2E suite"))
    for drill in DRILLS:
        acked = facts.manual_drills.get(drill, False)
        add(CheckResult("reliability", f"drill: {drill}",
            Status.PASS if acked else Status.MANUAL,
            "acknowledged" if acked else "run drill and record result in approval.md"))

    # ── performance evidence (graduation criteria, prd.md §3) ────────
    def evidence(name: str, value: float | int | None, ok: bool | None, req: str) -> None:
        if value is None or ok is None:
            add(CheckResult("performance", name, Status.FAIL, f"no data (need {req})"))
        else:
            add(CheckResult("performance", name,
                Status.PASS if ok else Status.FAIL, f"observed {value} (need {req})"))

    evidence("paper-trading duration", facts.paper_trading_days,
             None if facts.paper_trading_days is None
             else facts.paper_trading_days >= facts.required_paper_days,
             f">= {facts.required_paper_days} days")
    evidence("closed paper trades", facts.closed_paper_trades,
             None if facts.closed_paper_trades is None
             else facts.closed_paper_trades >= facts.required_trades,
             f">= {facts.required_trades}")
    evidence("net paper PnL after costs", facts.paper_net_pnl,
             None if facts.paper_net_pnl is None else facts.paper_net_pnl > 0, "> 0")
    evidence("max drawdown", facts.max_drawdown_pct,
             None if facts.max_drawdown_pct is None
             else facts.max_drawdown_pct <= facts.max_allowed_drawdown_pct,
             f"<= {facts.max_allowed_drawdown_pct}%")
    add(CheckResult("performance", "stability across periods (GC-6)",
        Status.MANUAL, "verify ≥2 of 3 consecutive 30-day windows positive"))
    add(CheckResult("performance", "multi-regime backtest evidence (GC-1)",
        Status.MANUAL, "≥2y per pair incl. up/down/range regimes; see performance-evidence.md"))
    add(CheckResult("performance", "model status",
        Status.PASS, f"deployed={facts.deployed_model or 'none (rule-based baselines)'}"))

    # ── gate ─────────────────────────────────────────────────────────
    add(CheckResult("gate", "owner sign-off recorded",
        Status.MANUAL, "docs/live-readiness/approval.md — final human decision"))
    return out


def verdict(results: list[CheckResult]) -> tuple[bool, str]:
    """(ready_for_owner_review, summary). Never 'ready for live' — that call
    belongs to the owner alone."""
    fails = [r for r in results if r.status is Status.FAIL]
    manuals = [r for r in results if r.status is Status.MANUAL]
    if fails:
        return False, (f"NOT READY: {len(fails)} failing check(s): "
                       + "; ".join(r.name for r in fails))
    return True, (f"READY FOR OWNER REVIEW: all automated checks pass; "
                  f"{len(manuals)} item(s) require manual verification and sign-off. "
                  "Passing this review does not guarantee future profitability.")
