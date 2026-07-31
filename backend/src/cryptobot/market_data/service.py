"""Market-data service: consume WS events, persist closed candles, backfill gaps.

Run via: `cryptobot collect`
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from cryptobot.core.logging import get_logger
from cryptobot.db.repositories import CandleRepository, InstrumentRepository
from cryptobot.db.session import SessionFactory
from cryptobot.exchange.binance.adapter import BinanceSpotAdapter
from cryptobot.exchange.models import MarketEventType
from cryptobot.market_data.staleness import StalenessMonitor

logger = get_logger(__name__)

_INTERVAL_TO_TIMEDELTA = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}


class MarketDataService:
    def __init__(
        self,
        adapter: BinanceSpotAdapter,
        session_factory: SessionFactory,
        symbols: list[str],
        intervals: list[str],
        staleness: StalenessMonitor,
    ) -> None:
        self._adapter = adapter
        self._sessions = session_factory
        self._symbols = symbols
        self._intervals = intervals
        self.staleness = staleness

    async def run(self) -> None:
        """Main loop: sync instruments, backfill, then stream."""
        await self._sync_instruments()
        await self._backfill_all()
        logger.info("market_data_streaming", symbols=self._symbols, intervals=self._intervals)
        async for event in self._adapter.market_stream(self._symbols, self._intervals):
            self.staleness.touch(event.symbol, event.received_at)
            if (
                event.type is MarketEventType.KLINE
                and event.candle is not None
                and event.candle.is_closed
            ):
                await self._persist_candle(event.candle)

    async def _sync_instruments(self) -> None:
        rules = await self._adapter.get_exchange_rules()
        async with self._sessions() as session:
            repo = InstrumentRepository(session)
            for symbol in self._symbols:
                symbol_rules = rules.symbols.get(symbol)
                if symbol_rules is None:
                    raise RuntimeError(f"{symbol} not present in exchangeInfo — check config")
                if not symbol_rules.is_trading:
                    logger.warning("symbol_not_trading", symbol=symbol, status=symbol_rules.status)
                await repo.upsert_from_rules(symbol_rules)
            await session.commit()
        logger.info("instruments_synced", count=len(self._symbols))

    async def _backfill_all(self, lookback: timedelta = timedelta(days=7)) -> None:
        """Fill candle gaps since the last stored candle (or `lookback`)."""
        for symbol in self._symbols:
            for interval in self._intervals:
                await self._backfill(symbol, interval, lookback)

    async def _backfill(self, symbol: str, interval: str, lookback: timedelta) -> None:
        async with self._sessions() as session:
            candle_repo = CandleRepository(session)
            last_open = await candle_repo.last_open_time(symbol, interval)
            start = (
                last_open + _INTERVAL_TO_TIMEDELTA[interval]
                if last_open
                else datetime.now(UTC) - lookback
            )
            total = 0
            while start < datetime.now(UTC):
                batch = await self._adapter.get_klines(symbol, interval, start=start, limit=1000)
                # Drop the still-open final candle
                closed = [
                    c
                    for c in batch
                    if c.open_time + _INTERVAL_TO_TIMEDELTA[interval] <= datetime.now(UTC)
                ]
                if not closed:
                    break
                await candle_repo.upsert_many(closed)
                total += len(closed)
                start = closed[-1].open_time + _INTERVAL_TO_TIMEDELTA[interval]
                if len(batch) < 1000:
                    break
            await session.commit()
            if total:
                logger.info("backfilled", symbol=symbol, interval=interval, candles=total)

    async def _persist_candle(self, candle: object) -> None:
        from cryptobot.exchange.models import Candle

        assert isinstance(candle, Candle)
        async with self._sessions() as session:
            await CandleRepository(session).upsert_many([candle])
            await session.commit()


async def watch_staleness(
    monitor: StalenessMonitor, symbols: list[str], check_every_s: float = 5.0
) -> None:
    """Background task: log/alert when any symbol's data goes stale."""
    alerted: set[str] = set()
    while True:
        await asyncio.sleep(check_every_s)
        stale = set(monitor.stale_symbols(symbols))
        for symbol in stale - alerted:
            logger.warning("market_data_stale", symbol=symbol, age_s=monitor.age_s(symbol))
        for symbol in alerted - stale:
            logger.info("market_data_recovered", symbol=symbol)
        alerted = stale
