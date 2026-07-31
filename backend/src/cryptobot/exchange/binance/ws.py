"""Binance WebSocket market streams with safe reconnection.

Combined-stream URL format (official docs):
  <ws_base>/stream?streams=btcusdt@kline_1m/ethusdt@trade
Testnet base: wss://stream.testnet.binance.vision

Reconnect policy: exponential backoff with jitter, resubscribe on connect,
and the consumer (MarketDataService) backfills gaps via REST klines.
"""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import websockets

from cryptobot.core.logging import get_logger
from cryptobot.exchange.models import Candle, MarketEvent, MarketEventType

logger = get_logger(__name__)


class BinanceMarketStream:
    def __init__(
        self,
        ws_base_url: str,
        symbols: list[str],
        intervals: list[str],
        include_trades: bool = False,
        max_backoff_s: float = 60.0,
    ) -> None:
        self._base = ws_base_url.rstrip("/")
        self._symbols = [s.lower() for s in symbols]
        self._intervals = intervals
        self._include_trades = include_trades
        self._max_backoff_s = max_backoff_s
        self.reconnect_count = 0
        self.last_event_at: datetime | None = None

    def _url(self) -> str:
        streams: list[str] = []
        for symbol in self._symbols:
            streams.extend(f"{symbol}@kline_{iv}" for iv in self._intervals)
            if self._include_trades:
                streams.append(f"{symbol}@trade")
        return f"{self._base}/stream?streams={'/'.join(streams)}"

    async def events(self) -> AsyncIterator[MarketEvent]:  # type: ignore[override]
        """Yield market events forever; reconnects internally."""
        attempt = 0
        while True:
            try:
                async with websockets.connect(
                    self._url(), ping_interval=20, ping_timeout=20, max_queue=1024
                ) as ws:
                    if attempt > 0:
                        self.reconnect_count += 1
                        logger.info("ws_reconnected", reconnects=self.reconnect_count)
                    attempt = 0
                    async for raw in ws:
                        event = self._parse(raw)
                        if event is not None:
                            self.last_event_at = event.received_at
                            yield event
            except asyncio.CancelledError:
                logger.info("ws_stream_cancelled")
                raise
            except Exception as exc:  # noqa: BLE001 — any network error → reconnect
                delay = min(2**attempt, self._max_backoff_s) + random.uniform(0, 1)
                logger.warning(
                    "ws_disconnected",
                    error=type(exc).__name__,
                    retry_in_s=round(delay, 1),
                    attempt=attempt,
                )
                await asyncio.sleep(delay)
                attempt += 1

    def _parse(self, raw: str | bytes) -> MarketEvent | None:
        try:
            message: dict[str, Any] = json.loads(raw)
        except (ValueError, TypeError):
            logger.warning("ws_unparseable_message")
            return None
        data = message.get("data", message)
        event_type = data.get("e")
        now = datetime.now(UTC)

        if event_type == "kline":
            k = data["k"]
            candle = Candle(
                symbol=str(data["s"]),
                interval=str(k["i"]),
                open_time=datetime.fromtimestamp(k["t"] / 1000, tz=UTC),
                open=Decimal(k["o"]),
                high=Decimal(k["h"]),
                low=Decimal(k["l"]),
                close=Decimal(k["c"]),
                volume=Decimal(k["v"]),
                quote_volume=Decimal(k["q"]),
                trade_count=int(k["n"]),
                is_closed=bool(k["x"]),
            )
            return MarketEvent(
                type=MarketEventType.KLINE, symbol=candle.symbol, received_at=now, candle=candle
            )
        if event_type == "trade":
            return MarketEvent(
                type=MarketEventType.TRADE,
                symbol=str(data["s"]),
                received_at=now,
                payload={"price": data["p"], "qty": data["q"], "trade_time": data["T"]},
            )
        return None
