"""Risk engine — absolute veto authority over every signal.

Shared by the backtester (Phase 3) and the paper/live pipelines (Phase 4+).
Defaults are the engineering defaults from docs/risk-policy.md — configurable,
never claimed optimal. Every rejection carries a machine-readable code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class RiskConfig:
    risk_per_trade: float = 0.005          # fraction of equity at risk per trade
    max_position_pct: float = 0.05         # max position notional / equity
    max_exposure_pct: float = 0.25         # max total exposure / equity
    max_positions: int = 3
    max_trades_per_day: int = 12
    max_daily_loss_pct: float = 0.02       # realized; halt + review
    max_drawdown_pct: float = 0.15         # from high-water mark; halt + review
    max_consecutive_losses: int = 5
    min_confidence: float = 0.6
    min_stop_distance_pct: float = 0.001   # stop must be a real stop


@dataclass
class RiskState:
    """Mutable per-run state the engine consults and the caller maintains."""

    equity: float = 0.0
    high_water_mark: float = 0.0
    open_positions: int = 0
    exposure_notional: float = 0.0
    trades_today: int = 0
    today: date | None = None
    daily_realized_pnl: float = 0.0
    consecutive_losses: int = 0
    halted: bool = False
    halt_reason: str = ""

    def roll_day(self, day: date) -> None:
        if self.today != day:
            self.today = day
            self.trades_today = 0
            self.daily_realized_pnl = 0.0

    def record_close(self, pnl: float) -> None:
        self.daily_realized_pnl += pnl
        self.consecutive_losses = 0 if pnl > 0 else self.consecutive_losses + 1

    def update_equity(self, equity: float) -> None:
        self.equity = equity
        self.high_water_mark = max(self.high_water_mark, equity)


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason_code: str
    detail: str = ""
    qty: float = 0.0

    @staticmethod
    def reject(code: str, detail: str = "") -> RiskDecision:
        return RiskDecision(approved=False, reason_code=code, detail=detail)


@dataclass
class BasicRiskEngine:
    config: RiskConfig = field(default_factory=RiskConfig)

    def check_halts(self, state: RiskState) -> RiskDecision | None:
        """Portfolio-level halt conditions (checked every bar, not per signal)."""
        cfg = self.config
        if state.halted:
            return RiskDecision.reject("HALTED", state.halt_reason)
        if state.equity > 0 and state.daily_realized_pnl <= -cfg.max_daily_loss_pct * state.equity:
            state.halted, state.halt_reason = True, "daily loss limit"
            return RiskDecision.reject("DAILY_LOSS_LIMIT", f"{state.daily_realized_pnl:.2f}")
        if (
            state.high_water_mark > 0
            and (state.high_water_mark - state.equity) / state.high_water_mark
            >= cfg.max_drawdown_pct
        ):
            state.halted, state.halt_reason = True, "max drawdown"
            return RiskDecision.reject("MAX_DRAWDOWN", f"hwm={state.high_water_mark:.2f}")
        if state.consecutive_losses >= cfg.max_consecutive_losses:
            state.halted, state.halt_reason = True, "consecutive losses"
            return RiskDecision.reject("CONSECUTIVE_LOSSES", str(state.consecutive_losses))
        return None

    def evaluate_entry(
        self,
        state: RiskState,
        confidence: float,
        price: float,
        stop_price: float | None,
        step_size: float = 1e-8,
        min_qty: float = 0.0,
        min_notional: float = 0.0,
    ) -> RiskDecision:
        """Veto or approve an entry and size the position. Order of checks
        follows docs/risk-policy.md §8 (portfolio halts before per-trade)."""
        cfg = self.config

        halt = self.check_halts(state)
        if halt is not None:
            return halt
        if state.trades_today >= cfg.max_trades_per_day:
            return RiskDecision.reject("MAX_TRADES_PER_DAY", str(state.trades_today))
        if state.open_positions >= cfg.max_positions:
            return RiskDecision.reject("MAX_POSITIONS", str(state.open_positions))
        if confidence < cfg.min_confidence:
            return RiskDecision.reject("LOW_CONFIDENCE", f"{confidence:.2f}")
        if stop_price is None:
            return RiskDecision.reject("NO_STOP", "entries without a stop are prohibited")
        if price <= 0 or stop_price >= price:
            return RiskDecision.reject("INVALID_STOP", f"stop {stop_price} vs price {price}")
        stop_distance = (price - stop_price) / price
        if stop_distance < cfg.min_stop_distance_pct:
            return RiskDecision.reject("STOP_TOO_TIGHT", f"{stop_distance:.4%}")

        # --- position sizing: risk a fixed fraction of equity to the stop ---
        risk_amount = state.equity * cfg.risk_per_trade
        qty = risk_amount / (price - stop_price)
        qty = min(qty, state.equity * cfg.max_position_pct / price)  # position cap
        headroom = state.equity * cfg.max_exposure_pct - state.exposure_notional
        if headroom <= 0:
            return RiskDecision.reject("MAX_EXPOSURE", f"exposure={state.exposure_notional:.2f}")
        qty = min(qty, headroom / price)

        qty = qty - (qty % step_size) if step_size > 0 else qty  # round DOWN
        if qty < min_qty or qty <= 0:
            return RiskDecision.reject("SIZE_BELOW_MIN_QTY", f"{qty}")
        if qty * price < min_notional:
            return RiskDecision.reject("SIZE_BELOW_MIN_NOTIONAL", f"{qty * price:.2f}")

        return RiskDecision(approved=True, reason_code="OK", qty=qty)
