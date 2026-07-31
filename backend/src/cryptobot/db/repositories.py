"""Repositories — thin, typed data access. All writes go through these."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from cryptobot.db.models import AuditEvent, CandleRow, Instrument, utcnow
from cryptobot.exchange.models import Candle, SymbolRules


class InstrumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_symbol(self, symbol: str) -> Instrument | None:
        result = await self._session.execute(
            select(Instrument).where(Instrument.symbol == symbol)
        )
        return result.scalar_one_or_none()

    async def upsert_from_rules(self, rules: SymbolRules) -> Instrument:
        instrument = await self.get_by_symbol(rules.symbol)
        if instrument is None:
            instrument = Instrument(symbol=rules.symbol, base_asset=rules.base_asset,
                                    quote_asset=rules.quote_asset, tick_size=rules.tick_size,
                                    step_size=rules.step_size, min_qty=rules.min_qty,
                                    max_qty=rules.max_qty, min_notional=rules.min_notional)
            self._session.add(instrument)
        instrument.status = rules.status
        instrument.tick_size = rules.tick_size
        instrument.step_size = rules.step_size
        instrument.min_qty = rules.min_qty
        instrument.max_qty = rules.max_qty
        instrument.min_notional = rules.min_notional
        instrument.filters_raw = {"filters": [dict(f) for f in rules.raw_filters]}
        instrument.filters_updated_at = utcnow()
        return instrument


class CandleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def last_open_time(self, symbol: str, interval: str) -> datetime | None:
        result = await self._session.execute(
            select(CandleRow.open_time)
            .where(CandleRow.symbol == symbol, CandleRow.interval == interval)
            .order_by(CandleRow.open_time.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # asyncpg limits a statement to 32,767 bound parameters (int16); at 11
    # columns per row, 1000 rows = 11,000 params — comfortably under it.
    _CHUNK_ROWS = 1000

    async def upsert_many(self, candles: list[Candle], source: str = "ws") -> None:
        if not candles:
            return
        rows = [
            {
                "symbol": c.symbol, "interval": c.interval, "open_time": c.open_time,
                "open": c.open, "high": c.high, "low": c.low, "close": c.close,
                "volume": c.volume, "quote_volume": c.quote_volume,
                "trade_count": c.trade_count, "source": source,
            }
            for c in candles
        ]
        dialect = self._session.bind.dialect.name if self._session.bind else "postgresql"
        insert = sqlite_insert if dialect == "sqlite" else pg_insert
        for start in range(0, len(rows), self._CHUNK_ROWS):
            chunk = rows[start : start + self._CHUNK_ROWS]
            stmt = insert(CandleRow).values(chunk)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["symbol", "interval", "open_time"]
            )
            await self._session.execute(stmt)

    async def count(self, symbol: str, interval: str) -> int:
        from sqlalchemy import func

        result = await self._session.execute(
            select(func.count())
            .select_from(CandleRow)
            .where(CandleRow.symbol == symbol, CandleRow.interval == interval)
        )
        return int(result.scalar_one())


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        category: str,
        payload: dict[str, object],
        actor: str = "system",
        correlation_id: object | None = None,
    ) -> None:
        from cryptobot.security.redaction import redact

        clean = {
            k: (redact(v) if isinstance(v, str) else v) for k, v in payload.items()
        }
        self._session.add(
            AuditEvent(category=category, actor=actor, payload=clean,
                       correlation_id=correlation_id)  # type: ignore[arg-type]
        )
