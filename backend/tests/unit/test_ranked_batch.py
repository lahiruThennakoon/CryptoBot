"""Ranked batch entry allocation tests."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cryptobot.costs.model import CostModel
from cryptobot.decision.scoring import DecisionScorer, Gates
from cryptobot.exchange.models import Candle
from cryptobot.paper.account import PaperAccount
from cryptobot.paper.broker import PaperBroker
from cryptobot.regime.detector import Regime
from cryptobot.risk.engine import BasicRiskEngine, RiskConfig
from cryptobot.runtime.engine import TradingRuntime
from cryptobot.strategies.base import HOLD, Intent, Signal, Strategy, StrategySpec

D = Decimal
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _candle(i: int, symbol: str, close: float) -> Candle:
    return Candle(
        symbol=symbol, interval="1h",
        open_time=T0 + timedelta(hours=i),
        open=D(str(close)), high=D(str(close * 1.001)),
        low=D(str(close * 0.999)), close=D(str(close)),
        volume=D("10"), quote_volume=D("1000"), trade_count=5, is_closed=True,
    )


class EnterOnce(Strategy):
    def __init__(self, symbol: str, at_bar: int = 62):
        self._at = at_bar
        self._fired = False
        self.spec = StrategySpec(
            name=f"enter_{symbol.lower()}",
            timeframe="1h",
            warmup_bars=5,
            max_holding_bars=48,
            cooldown_bars=0,
            pairs=(symbol,),
            allowed_regimes=frozenset(Regime),
        )

    def on_bar(self, bars, i):
        if i >= self._at and not self._fired:
            self._fired = True
            price = float(bars[i].close)
            return Signal(
                Intent.ENTER_LONG,
                confidence=0.9,
                stop_price=price * 0.95,
                take_profit=price * 1.2,
            )
        return HOLD


class TestRankedBatch:
    async def test_waits_for_all_enabled_pairs_before_batch(self):
        costs = CostModel(safety_margin=0.0)
        eth = EnterOnce("ETHUSDT")
        scorer = DecisionScorer(
            [eth],
            costs=costs,
            gates=Gates(buy_threshold=0.15, strong_buy_threshold=0.4),
        )
        executions: list[str] = []

        async def enabled() -> set[str]:
            return {"BTCUSDT", "ETHUSDT"}

        runtime = TradingRuntime(
            broker=PaperBroker(PaperAccount.with_starting_balance("USDT", D("10000")), costs),
            strategies=[eth],
            risk=BasicRiskEngine(RiskConfig(min_confidence=0.25, max_positions=1)),
            costs=costs,
            decision_scorer=scorer,
            enabled_pairs=enabled,
        )
        runtime.events.on_execution = lambda *a: executions.append(a[0].symbol)

        for i in range(62):
            await runtime.on_closed_candle(_candle(i, "BTCUSDT", 100.0))
            await runtime.on_closed_candle(_candle(i, "ETHUSDT", 50.0))

        await runtime.on_closed_candle(_candle(62, "BTCUSDT", 100.0))
        assert not executions

        await runtime.on_closed_candle(_candle(62, "ETHUSDT", 50.0))
        assert len(executions) == 1

    async def test_batch_runs_once_per_bar_period(self):
        costs = CostModel(safety_margin=0.0)
        strategy = EnterOnce("BTCUSDT")
        scorer = DecisionScorer([strategy], costs=costs, gates=Gates(buy_threshold=0.15))
        executions: list[object] = []
        runtime = TradingRuntime(
            broker=PaperBroker(PaperAccount.with_starting_balance("USDT", D("10000")), costs),
            strategies=[strategy],
            risk=BasicRiskEngine(RiskConfig(min_confidence=0.25)),
            costs=costs,
            decision_scorer=scorer,
        )
        runtime.events.on_execution = lambda *a: executions.append(a)

        for i in range(63):
            await runtime.on_closed_candle(_candle(i, "BTCUSDT", 100.0))

        assert len(executions) == 1
