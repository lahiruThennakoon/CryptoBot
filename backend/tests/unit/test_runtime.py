"""Trading-runtime pipeline tests with a scripted strategy and synthetic candles."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cryptobot.costs.model import CostModel
from cryptobot.decision.scoring import DecisionScorer, Gates
from cryptobot.exchange.models import Candle
from cryptobot.paper.account import PaperAccount
from cryptobot.paper.broker import PaperBroker
from cryptobot.regime.detector import Regime
from cryptobot.risk.engine import BasicRiskEngine, RiskConfig
from cryptobot.runtime.engine import RuntimeEvents, TradingRuntime
from cryptobot.strategies.base import HOLD, Intent, Signal, Strategy, StrategySpec

D = Decimal
T0 = datetime(2026, 1, 1, tzinfo=UTC)
MIN_BARS = 65


def candle(i: int, close: float = 100.0, low: float | None = None,
           high: float | None = None, interval: str = "1h",
           symbol: str = "BTCUSDT") -> Candle:
    return Candle(
        symbol=symbol, interval=interval,
        open_time=T0 + timedelta(hours=i),
        open=D(str(close)), high=D(str(high if high is not None else close * 1.001)),
        low=D(str(low if low is not None else close * 0.999)), close=D(str(close)),
        volume=D("10"), quote_volume=D("1000"), trade_count=5, is_closed=True,
    )


class EnterOnce(Strategy):
    def __init__(self, at_bar: int = 62, stop_pct: float = 0.05):
        self._at, self._stop_pct, self.fired = at_bar, stop_pct, False
        self.spec = StrategySpec(
            name="enter_once", timeframe="1h", warmup_bars=5, max_holding_bars=1000,
            cooldown_bars=0, allowed_regimes=frozenset(Regime),
        )

    def on_bar(self, bars, i):
        if i >= self._at and not self.fired:
            self.fired = True
            price = float(bars[i].close)
            return Signal(Intent.ENTER_LONG, confidence=0.9,
                          stop_price=price * (1 - self._stop_pct),
                          take_profit=price * 1.2)
        return HOLD


@dataclass
class Captured:
    signals: list = field(default_factory=list)
    executions: list = field(default_factory=list)
    closes: list = field(default_factory=list)
    risk_events: list = field(default_factory=list)
    decisions: list = field(default_factory=list)


def make_runtime(strategy: Strategy, captured: Captured, controls=None) -> TradingRuntime:
    costs = CostModel(safety_margin=0.0)
    scorer = DecisionScorer(
        [strategy],
        costs=costs,
        gates=Gates(buy_threshold=0.2, strong_buy_threshold=0.5),
    )
    events = RuntimeEvents()
    events.on_signal = lambda *a: captured.signals.append(a)
    events.on_execution = lambda *a: captured.executions.append(a)
    events.on_position_close = lambda *a: captured.closes.append(a)
    events.on_risk_event = lambda *a: captured.risk_events.append(a)
    events.on_decision = lambda *a: captured.decisions.append(a[0])
    return TradingRuntime(
        broker=PaperBroker(PaperAccount.with_starting_balance("USDT", D("10000")), costs),
        strategies=[strategy],
        risk=BasicRiskEngine(RiskConfig(min_confidence=0.4)),
        costs=costs,
        events=events,
        controls_state=controls,
        decision_scorer=scorer,
    )


async def feed(runtime: TradingRuntime, candles: list[Candle]) -> None:
    for c in candles:
        await runtime.on_closed_candle(c)


class TestPipeline:
    async def test_signal_to_execution_to_position(self):
        captured = Captured()
        runtime = make_runtime(EnterOnce(at_bar=62), captured)
        await feed(runtime, [candle(i) for i in range(MIN_BARS)])
        executed = [s for s in captured.signals if s[5] == "executed"]
        assert len(executed) == 1
        assert executed[0][1] == "ranked_batch"
        assert len(captured.executions) == 1
        assert runtime.snapshot()["open_positions"] == 1
        assert captured.decisions

    async def test_stop_loss_closes_position(self):
        captured = Captured()
        runtime = make_runtime(EnterOnce(at_bar=62, stop_pct=0.05), captured)
        candles = [candle(i) for i in range(MIN_BARS)]
        candles.append(candle(MIN_BARS, close=94.0, low=90.0))
        await feed(runtime, candles)
        assert runtime.snapshot()["open_positions"] == 0
        assert captured.closes and captured.closes[0][3] == "stop_loss"

    async def test_duplicate_candles_are_idempotent(self):
        captured = Captured()
        runtime = make_runtime(EnterOnce(at_bar=62), captured)
        candles = [candle(i) for i in range(MIN_BARS)]
        await feed(runtime, candles + candles[-5:])
        assert len(captured.executions) == 1

    async def test_daily_loss_halt_blocks_new_entries(self):
        captured = Captured()

        class EnterAlways(EnterOnce):
            def on_bar(self, bars, i):
                if i >= 62:
                    price = float(bars[i].close)
                    return Signal(Intent.ENTER_LONG, confidence=0.9,
                                  stop_price=price * 0.95, take_profit=price * 1.2)
                return HOLD

        runtime = make_runtime(EnterAlways(), captured)
        runtime._risk_state.daily_realized_pnl = -1000.0
        runtime.seed_equity(10_000.0)
        await feed(runtime, [candle(i) for i in range(MIN_BARS)])
        assert not captured.executions
        rejects = {s[6] for s in captured.signals}
        assert "DAILY_LOSS_LIMIT" in rejects or "HALTED" in rejects


class TestEmergencyStop:
    async def test_emergency_stop_closes_all_positions(self):
        captured = Captured()
        runtime = make_runtime(EnterOnce(at_bar=62), captured)
        await feed(runtime, [candle(i) for i in range(MIN_BARS)])
        assert runtime.snapshot()["open_positions"] == 1
        closed = await runtime.execute_emergency_stop()
        assert closed == 1
        assert runtime.snapshot()["open_positions"] == 0
        assert captured.closes[0][3] == "emergency_stop"
        assert any(e[0] == "emergency_stop" for e in captured.risk_events)

    async def test_paused_controls_block_trading(self):
        class PausedState:
            paused, emergency_stop, trading_allowed = True, False, False

        async def controls():
            return PausedState()

        captured = Captured()
        runtime = make_runtime(EnterOnce(at_bar=62), captured, controls=controls)
        await feed(runtime, [candle(i) for i in range(MIN_BARS)])
        assert not captured.executions
