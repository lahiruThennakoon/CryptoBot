"""Historical kline importer with data-quality validation.

Rejects/reports: duplicates, out-of-order candles, gaps, non-positive prices,
high/low inconsistencies. Imported data is only trusted for backtesting when
validation reports zero critical issues.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from cryptobot.core.logging import get_logger
from cryptobot.db.repositories import CandleRepository
from cryptobot.db.session import SessionFactory
from cryptobot.exchange.binance.adapter import BinanceSpotAdapter
from cryptobot.exchange.models import Candle

logger = get_logger(__name__)

INTERVAL_TD = {
    "1m": timedelta(minutes=1), "5m": timedelta(minutes=5), "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1), "4h": timedelta(hours=4), "1d": timedelta(days=1),
}


@dataclass
class ValidationIssues:
    duplicates: int = 0
    out_of_order: int = 0
    gaps: list[tuple[datetime, datetime]] = field(default_factory=list)
    bad_values: int = 0

    @property
    def critical(self) -> bool:
        return bool(self.duplicates or self.out_of_order or self.bad_values or self.gaps)

    def summary(self) -> str:
        return (
            f"duplicates={self.duplicates} out_of_order={self.out_of_order} "
            f"gaps={len(self.gaps)} bad_values={self.bad_values}"
        )


def validate_candles(candles: list[Candle], interval: str) -> ValidationIssues:
    issues = ValidationIssues()
    step = INTERVAL_TD[interval]
    seen: set[datetime] = set()
    prev: datetime | None = None
    for c in candles:
        if c.open_time in seen:
            issues.duplicates += 1
            continue
        seen.add(c.open_time)
        if prev is not None:
            if c.open_time <= prev:
                issues.out_of_order += 1
            elif c.open_time - prev > step:
                issues.gaps.append((prev + step, c.open_time))
        if (
            c.open <= 0 or c.high <= 0 or c.low <= 0 or c.close <= 0
            or c.high < c.low
            or c.high < max(c.open, c.close)
            or c.low > min(c.open, c.close)
        ):
            issues.bad_values += 1
        prev = c.open_time
    return issues


class HistoricalImporter:
    def __init__(self, adapter: BinanceSpotAdapter, sessions: SessionFactory) -> None:
        self._adapter = adapter
        self._sessions = sessions

    async def import_range(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime | None = None,
        batch_limit: int = 1000,
    ) -> tuple[int, ValidationIssues]:
        """Download, validate and persist klines. Returns (count, issues)."""
        end = end or datetime.now(UTC)
        step = INTERVAL_TD[interval]
        all_candles: list[Candle] = []
        cursor = start
        while cursor < end:
            batch = await self._adapter.get_klines(
                symbol, interval, start=cursor, end=end, limit=batch_limit
            )
            if not batch:
                break
            closed = [c for c in batch if c.open_time + step <= datetime.now(UTC)]
            if not closed:
                break
            all_candles.extend(closed)
            cursor = closed[-1].open_time + step
            if len(batch) < batch_limit:
                break

        issues = validate_candles(all_candles, interval)
        if issues.gaps:
            # one retry pass over gaps (exchange outages produce real gaps that
            # cannot be filled; they remain reported)
            for gap_start, gap_end in list(issues.gaps):
                patch = await self._adapter.get_klines(
                    symbol, interval, start=gap_start, end=gap_end, limit=batch_limit
                )
                all_candles.extend(c for c in patch if c.open_time not in
                                   {x.open_time for x in all_candles})
            all_candles.sort(key=lambda c: c.open_time)
            issues = validate_candles(all_candles, interval)

        async with self._sessions() as session:
            await CandleRepository(session).upsert_many(all_candles, source="import")
            await session.commit()
        logger.info(
            "history_imported",
            symbol=symbol, interval=interval, candles=len(all_candles),
            issues=issues.summary(),
        )
        return len(all_candles), issues
