"""Trading-session policy (pure): times, days, overnight, profit-target protection.

The daily objective is a positive NET result after all costs — but daily
profit is never guaranteed and never forced: the bot must not manufacture
trades to hit a target nor raise risk to recover a loss. When a configured
target is reached, the conservative default STOPS new entries for the day.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum


class OvernightPolicy(str, Enum):
    HOLD = "hold"
    CLOSE_AT_SESSION_END = "close_at_session_end"


class TargetProtection(str, Enum):
    STOP_TRADING = "stop_trading"          # conservative default
    REDUCE_SIZE = "reduce_size"
    RAISE_CONFIDENCE = "raise_confidence"
    EXCEPTIONAL_ONLY = "exceptional_only"


@dataclass(frozen=True)
class SessionConfig:
    session_start_utc: str = "00:00"
    session_end_utc: str = "23:59"
    trading_days: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6)   # Monday=0
    overnight_policy: OvernightPolicy = OvernightPolicy.HOLD
    daily_profit_target_pct: float | None = None            # e.g. 0.01 = 1%
    target_protection: TargetProtection = TargetProtection.STOP_TRADING
    reduce_size_factor: float = 0.5
    raised_min_confidence: float = 0.8
    exceptional_score: float = 0.75
    max_capital: float | None = None


def validate_config(cfg: SessionConfig, cost_floor_fraction: float = 0.004) -> list[str]:
    """Returns a list of human-readable problems; empty list = valid.
    Rejects unsafe or contradictory combinations (docs/spec-v2 FR-17.3)."""
    problems: list[str] = []
    try:
        start = _parse(cfg.session_start_utc)
        end = _parse(cfg.session_end_utc)
        if end <= start:
            problems.append("Session end must be after session start (UTC times).")
    except ValueError:
        problems.append("Session times must be HH:MM in 24h UTC.")
    if not cfg.trading_days:
        problems.append("At least one trading day must be enabled.")
    if any(d not in range(7) for d in cfg.trading_days):
        problems.append("Trading days must be 0 (Monday) through 6 (Sunday).")
    if cfg.daily_profit_target_pct is not None:
        if cfg.daily_profit_target_pct <= 0:
            problems.append("Daily profit target must be positive (or unset).")
        elif cfg.daily_profit_target_pct < cost_floor_fraction:
            problems.append(
                f"Daily profit target {cfg.daily_profit_target_pct:.2%} is below the "
                f"round-trip cost floor {cost_floor_fraction:.2%} — it would pressure "
                "the bot into trades that cannot pay for themselves."
            )
        elif cfg.daily_profit_target_pct > 0.05:
            problems.append(
                "Daily profit targets above 5% require risk levels this system "
                "refuses to take. Lower the target."
            )
    if not 0 < cfg.reduce_size_factor <= 1:
        problems.append("Size-reduction factor must be between 0 and 1.")
    if not 0 < cfg.raised_min_confidence <= 1:
        problems.append("Raised confidence must be between 0 and 1.")
    if cfg.max_capital is not None and cfg.max_capital <= 0:
        problems.append("Max capital must be positive (or unset).")
    return problems


@dataclass(frozen=True)
class EntryPolicy:
    """What the session layer permits for NEW entries right now."""

    allowed: bool
    reason_code: str = ""
    detail: str = ""
    size_factor: float = 1.0            # 1.0 = normal sizing
    min_confidence_override: float | None = None
    min_score_override: float | None = None


@dataclass
class SessionState:
    day_start_equity: float = 0.0
    realized_pnl_today: float = 0.0
    target_reached_notified: bool = field(default=False)


def evaluate_entry_policy(
    cfg: SessionConfig, state: SessionState, now_utc: datetime
) -> EntryPolicy:
    if now_utc.weekday() not in cfg.trading_days:
        return EntryPolicy(False, "OUT_OF_SESSION", "Today is not an enabled trading day.")
    now_t = now_utc.time()
    if not (_parse(cfg.session_start_utc) <= now_t <= _parse(cfg.session_end_utc)):
        return EntryPolicy(False, "OUT_OF_SESSION",
                           f"Outside the configured session "
                           f"({cfg.session_start_utc}–{cfg.session_end_utc} UTC).")

    if cfg.daily_profit_target_pct is not None and state.day_start_equity > 0:
        progress = state.realized_pnl_today / state.day_start_equity
        if progress >= cfg.daily_profit_target_pct:
            mode = cfg.target_protection
            if mode is TargetProtection.STOP_TRADING:
                return EntryPolicy(
                    False, "PROFIT_TARGET_REACHED",
                    f"Daily target {cfg.daily_profit_target_pct:.2%} reached "
                    f"({progress:.2%} realized). Protecting the result: no new "
                    "trades today. Exits remain active.",
                )
            if mode is TargetProtection.REDUCE_SIZE:
                return EntryPolicy(
                    True, "PROFIT_TARGET_REDUCED_SIZE",
                    "Daily target reached — position sizes reduced to protect gains.",
                    size_factor=cfg.reduce_size_factor,
                )
            if mode is TargetProtection.RAISE_CONFIDENCE:
                return EntryPolicy(
                    True, "PROFIT_TARGET_RAISED_BAR",
                    "Daily target reached — only high-confidence signals accepted now.",
                    min_confidence_override=cfg.raised_min_confidence,
                )
            if mode is TargetProtection.EXCEPTIONAL_ONLY:
                return EntryPolicy(
                    True, "PROFIT_TARGET_EXCEPTIONAL_ONLY",
                    "Daily target reached — only exceptionally strong opportunities "
                    "will be considered.",
                    min_score_override=cfg.exceptional_score,
                )
    return EntryPolicy(True)


def session_ended(cfg: SessionConfig, now_utc: datetime) -> bool:
    return now_utc.time() > _parse(cfg.session_end_utc) or (
        now_utc.weekday() not in cfg.trading_days
    )


def _parse(hhmm: str) -> time:
    hours, minutes = hhmm.split(":")
    return time(int(hours), int(minutes))
