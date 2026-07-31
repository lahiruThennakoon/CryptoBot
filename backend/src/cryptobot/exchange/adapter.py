"""ExchangeAdapter protocol — the only surface the rest of the system sees.

Implementations: BinanceSpotAdapter (testnet/live via config), PaperAdapter.
A future exchange requires a new adapter and zero changes elsewhere.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Protocol

from cryptobot.exchange.models import (
    AccountState,
    Candle,
    ExchangeRules,
    MarketEvent,
    OrderBook,
    OrderRequest,
    OrderState,
)


class ExchangeAdapter(Protocol):
    async def get_server_time(self) -> datetime: ...

    async def get_exchange_rules(self) -> ExchangeRules: ...

    async def get_account(self) -> AccountState: ...

    async def get_order_book(self, symbol: str, limit: int = 20) -> OrderBook: ...

    async def get_klines(
        self,
        symbol: str,
        interval: str,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> list[Candle]: ...

    async def place_order(self, request: OrderRequest) -> OrderState:
        """Submit an order. request.client_order_id is the idempotency key.

        On any ambiguous failure the caller MUST call query_order before
        retrying — never blind-resubmit.
        """
        ...

    async def cancel_order(self, symbol: str, client_order_id: str) -> OrderState: ...

    async def query_order(self, symbol: str, client_order_id: str) -> OrderState: ...

    async def get_open_orders(self, symbol: str | None = None) -> list[OrderState]: ...

    def market_stream(
        self, symbols: list[str], intervals: list[str]
    ) -> AsyncIterator[MarketEvent]: ...

    async def close(self) -> None: ...
