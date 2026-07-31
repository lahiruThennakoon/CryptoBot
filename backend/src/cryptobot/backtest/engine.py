"""Event-driven backtest engine.

Anti-bias construction:
- Signals computed on bar i execute at bar i+1's OPEN — never the same bar.
- Strategies receive only bars[0..i] (enforced by the no-look-ahead test).
- Fills pay half-spread + slippage + latency drift + taker fees (CostModel).
- Stops/TPs are evaluated conservatively: gap-through-stop fills at the open,
  never at the stop; if stop and TP are both touched in one bar, the STOP wins.
- No fills at candle extremes; entry fills never better than the open.
- Exchange filters (step size, min qty, min notional) applied to sizing.

Phase 3 limitation (documented): entries are simulated as marketable orders
at next open; resting limit-order queues are not modeled. Costs therefore use
taker fees — the conservative choice.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from cryptobot.costs.model import CostModel
from cryptobot.regime.detector import Regime, RegimeDetector
from cryptobot.risk.engine import BasicRiskEngine, RiskState
from cryptobot.strategies.base import BarLike, Intent, Strategy


@dataclass(frozen=True)
class SimpleRules:
    """Exchange-filter subset used in simulation."""

    step_size: float = 1e-5
    min_qty: float = 1e-5
    min_notional: float = 5.0


@dataclass(frozen=True)
class ClosedTrade:
    entry_time: datetime
    exit_time: datetime
    entry_price: float          # actual fill incl. costs
    exit_price: float
    qty: float
    fees: float
    slippage_cost: float        # fill price vs reference-open difference
    pnl: float                  # net of fees and slippage
    exit_reason: str
    bars_held: int
    regime_at_entry: str


@dataclass(frozen=True)
class RejectedSignal:
    time: datetime
    reason_code: str
    detail: str


@dataclass
class BacktestResult:
    trades: list[ClosedTrade] = field(default_factory=list)
    rejected: list[RejectedSignal] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    equity_times: list[datetime] = field(default_factory=list)
    buy_hold_curve: list[float] = field(default_factory=list)
    initial_equity: float = 0.0
    total_fees: float = 0.0
    total_slippage: float = 0.0
    halted: bool = False
    halt_reason: str = ""
    bars_in_position: int = 0
    regime_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class _OpenPosition:
    qty: float
    entry_price: float
    entry_ref: float
    stop: float
    take_profit: float | None
    entry_index: int
    entry_time: datetime
    entry_fee: float
    entry_slip: float
    regime: str


class BacktestEngine:
    def __init__(
        self,
        costs: CostModel | None = None,
        risk: BasicRiskEngine | None = None,
        rules: SimpleRules | None = None,
        initial_equity: float = 10_000.0,
        use_regime_filter: bool = True,
    ) -> None:
        self._costs = costs or CostModel()
        self._risk = risk or BasicRiskEngine()
        self._rules = rules or SimpleRules()
        self._initial_equity = initial_equity
        self._use_regime_filter = use_regime_filter

    def run(self, bars: Sequence[BarLike], strategy: Strategy) -> BacktestResult:
        if len(bars) < strategy.spec.warmup_bars + 2:
            raise ValueError("not enough bars for strategy warmup")

        strategy.prepare(bars)
        regimes = self._regimes(bars)

        result = BacktestResult(initial_equity=self._initial_equity)
        for regime in regimes:
            result.regime_counts[regime.value] = result.regime_counts.get(regime.value, 0) + 1
        state = RiskState(equity=self._initial_equity, high_water_mark=self._initial_equity)
        cash = self._initial_equity
        position: _OpenPosition | None = None
        cooldown_until = -1
        pending_entry: tuple[int, float, float | None, str] | None = None  # (i, stop, tp, regime)
        pending_exit_reason: str | None = None

        first_open = float(bars[strategy.spec.warmup_bars + 1].open)  # type: ignore[arg-type]

        for i in range(strategy.spec.warmup_bars, len(bars)):
            bar = bars[i]
            open_px = float(bar.open)  # type: ignore[arg-type]
            state.roll_day(bar.open_time.date())

            # ── execute pending exit (signaled at bar i-1) at THIS bar's open ──
            if position is not None and pending_exit_reason is not None:
                cash = self._close(result, state, position, open_px, bar.open_time,
                                   i, pending_exit_reason, cash)
                position, pending_exit_reason = None, None
                cooldown_until = i + strategy.spec.cooldown_bars

            # ── execute pending entry (signaled at bar i-1) at THIS bar's open ──
            if pending_entry is not None and position is None and not state.halted:
                sig_i, stop, tp, regime = pending_entry
                decision = self._risk.evaluate_entry(
                    state,
                    confidence=1.0,  # confidence already checked at signal time
                    price=open_px,
                    stop_price=stop,
                    step_size=self._rules.step_size,
                    min_qty=self._rules.min_qty,
                    min_notional=self._rules.min_notional,
                )
                if decision.approved:
                    fill = self._costs.buy_fill_price(open_px)
                    fee = self._costs.fee(decision.qty * fill, taker=True)
                    if decision.qty * fill + fee <= cash:
                        cash -= decision.qty * fill + fee
                        position = _OpenPosition(
                            qty=decision.qty, entry_price=fill, entry_ref=open_px,
                            stop=stop, take_profit=tp, entry_index=i,
                            entry_time=bar.open_time, entry_fee=fee,
                            entry_slip=(fill - open_px) * decision.qty, regime=regime,
                        )
                        state.open_positions = 1
                        state.exposure_notional = decision.qty * fill
                        state.trades_today += 1
                    else:
                        result.rejected.append(RejectedSignal(
                            bar.open_time, "INSUFFICIENT_CASH", f"{cash:.2f}"))
                else:
                    result.rejected.append(RejectedSignal(
                        bar.open_time, decision.reason_code, decision.detail))
                pending_entry = None

            # ── manage open position on THIS bar (stop/TP/max-hold) ──
            if position is not None:
                exit_price, reason = self._protective_exit(position, bar)
                if exit_price is not None and reason is not None:
                    cash = self._close(result, state, position, exit_price,
                                       bar.open_time, i, reason, cash, is_stop_level=True)
                    position = None
                    cooldown_until = i + strategy.spec.cooldown_bars
                elif i - position.entry_index >= strategy.spec.max_holding_bars:
                    pending_exit_reason = "max_holding_period"

            # ── mark to market ───────────────────────────────────────
            close_px = float(bar.close)  # type: ignore[arg-type]
            equity = cash + (position.qty * close_px if position else 0.0)
            state.update_equity(equity)
            state.exposure_notional = position.qty * close_px if position else 0.0
            result.equity_curve.append(equity)
            result.equity_times.append(bar.open_time)
            if i > strategy.spec.warmup_bars:
                result.buy_hold_curve.append(
                    self._initial_equity
                    * (1 - self._costs.round_trip_fraction / 2)
                    * float(bar.close) / first_open  # type: ignore[arg-type]
                )
            else:
                result.buy_hold_curve.append(self._initial_equity)
            if position is not None:
                result.bars_in_position += 1

            halt = self._risk.check_halts(state)
            if halt is not None and position is None:
                result.halted, result.halt_reason = True, halt.reason_code
                break

            # ── strategy decision on bar i → executes at bar i+1 ─────
            signal = strategy.on_bar(bars, i)
            if signal.intent is Intent.EXIT and position is not None:
                pending_exit_reason = signal.reason or "strategy_exit"
            elif signal.intent is Intent.ENTER_LONG and position is None:
                if state.halted:
                    result.rejected.append(RejectedSignal(bar.open_time, "HALTED", state.halt_reason))
                elif i < cooldown_until:
                    result.rejected.append(RejectedSignal(bar.open_time, "COOLDOWN", ""))
                elif signal.confidence < self._risk.config.min_confidence:
                    result.rejected.append(RejectedSignal(
                        bar.open_time, "LOW_CONFIDENCE", f"{signal.confidence:.2f}"))
                elif self._use_regime_filter and regimes[i] not in strategy.spec.allowed_regimes:
                    result.rejected.append(RejectedSignal(
                        bar.open_time, "REGIME_EXCLUDED", regimes[i].value))
                elif signal.stop_price is None:
                    result.rejected.append(RejectedSignal(bar.open_time, "NO_STOP", ""))
                else:
                    expected_move = (
                        (signal.take_profit / close_px - 1)
                        if signal.take_profit
                        else (close_px - signal.stop_price) / close_px  # 1R proxy
                    )
                    if not self._costs.passes_cost_gate(expected_move):
                        result.rejected.append(RejectedSignal(
                            bar.open_time, "COST_GATE",
                            f"edge {expected_move:.4f} ≤ costs {self._costs.round_trip_fraction:.4f}"))
                    else:
                        pending_entry = (i, signal.stop_price, signal.take_profit,
                                         regimes[i].value)

        # ── close any open position at the last bar's close ──────────
        if position is not None:
            last = bars[-1]
            cash = self._close(result, state, position, float(last.close),  # type: ignore[arg-type]
                               last.open_time, len(bars) - 1, "end_of_data", cash)
        result.total_fees = sum(t.fees for t in result.trades)
        result.total_slippage = sum(t.slippage_cost for t in result.trades)
        return result

    # ── helpers ──────────────────────────────────────────────────────
    def _regimes(self, bars: Sequence[BarLike]) -> list[Regime]:
        if not self._use_regime_filter:
            return [Regime.UNKNOWN] * len(bars)
        detector = RegimeDetector()
        return detector.classify_series(
            [float(b.high) for b in bars],   # type: ignore[arg-type]
            [float(b.low) for b in bars],    # type: ignore[arg-type]
            [float(b.close) for b in bars],  # type: ignore[arg-type]
        )

    @staticmethod
    def _protective_exit(
        position: _OpenPosition, bar: BarLike
    ) -> tuple[float | None, str | None]:
        """Conservative stop/TP evaluation. Stop has priority over TP."""
        o = float(bar.open)   # type: ignore[arg-type]
        h = float(bar.high)   # type: ignore[arg-type]
        low = float(bar.low)  # type: ignore[arg-type]
        if o <= position.stop:
            return o, "stop_loss_gap"      # gapped through: fill at open, not the stop
        if low <= position.stop:
            return position.stop, "stop_loss"
        if position.take_profit is not None:
            if o >= position.take_profit:
                return o, "take_profit_gap"
            if h >= position.take_profit:
                return position.take_profit, "take_profit"
        return None, None

    def _close(
        self,
        result: BacktestResult,
        state: RiskState,
        position: _OpenPosition,
        reference_price: float,
        time: datetime,
        index: int,
        reason: str,
        cash: float,
        is_stop_level: bool = False,
    ) -> float:
        fill = self._costs.sell_fill_price(reference_price)
        fee = self._costs.fee(position.qty * fill, taker=True)
        proceeds = position.qty * fill - fee
        slip = (reference_price - fill) * position.qty + position.entry_slip
        pnl = proceeds - position.qty * position.entry_price - position.entry_fee
        result.trades.append(ClosedTrade(
            entry_time=position.entry_time, exit_time=time,
            entry_price=position.entry_price, exit_price=fill, qty=position.qty,
            fees=position.entry_fee + fee, slippage_cost=slip, pnl=pnl,
            exit_reason=reason, bars_held=index - position.entry_index,
            regime_at_entry=position.regime,
        ))
        state.open_positions = 0
        state.exposure_notional = 0.0
        state.record_close(pnl)
        return cash + proceeds
