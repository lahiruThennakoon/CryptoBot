"""BinanceSpotAdapter — ExchangeAdapter implementation over REST + WS.

Endpoints used (official Spot API, /api/v3):
  GET  /v3/time, /v3/exchangeInfo, /v3/klines, /v3/depth
  GET  /v3/account (signed)
  POST /v3/order (signed) · DELETE /v3/order (signed)
  GET  /v3/order (signed) · GET /v3/openOrders (signed)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from cryptobot.core.logging import get_logger
from cryptobot.exchange.errors import ExchangeError
from cryptobot.exchange.models import (
    AccountState,
    Balance,
    BookLevel,
    Candle,
    ExchangeRules,
    Fill,
    MarketEvent,
    OrderBook,
    OrderRequest,
    OrderState,
    OrderStatus,
    OrderType,
    Side,
    SymbolRules,
)
from cryptobot.exchange.binance.client import BinanceRestClient
from cryptobot.exchange.binance.ws import BinanceMarketStream

logger = get_logger(__name__)

_D = Decimal


def _parse_symbol_rules(entry: dict[str, Any]) -> SymbolRules:
    filters = {f["filterType"]: f for f in entry.get("filters", [])}
    price_filter = filters.get("PRICE_FILTER", {})
    lot = filters.get("LOT_SIZE", {})
    notional = filters.get("NOTIONAL", filters.get("MIN_NOTIONAL", {}))
    return SymbolRules(
        symbol=entry["symbol"],
        base_asset=entry["baseAsset"],
        quote_asset=entry["quoteAsset"],
        status=entry["status"],
        tick_size=_D(price_filter.get("tickSize", "0.00000001")),
        step_size=_D(lot.get("stepSize", "0.00000001")),
        min_qty=_D(lot.get("minQty", "0")),
        max_qty=_D(lot.get("maxQty", "9000000000")),
        min_notional=_D(notional.get("minNotional", "0")),
        raw_filters=tuple(
            {str(k): str(v) for k, v in f.items()} for f in entry.get("filters", [])
        ),
    )


def _parse_order_state(data: dict[str, Any]) -> OrderState:
    fills = tuple(
        Fill(
            trade_id=str(f.get("tradeId", i)),
            price=_D(f["price"]),
            qty=_D(f["qty"]),
            fee_amount=_D(f.get("commission", "0")),
            fee_asset=str(f.get("commissionAsset", "")),
        )
        for i, f in enumerate(data.get("fills", []))
    )
    raw_status = str(data.get("status", "UNKNOWN"))
    try:
        status = OrderStatus(raw_status)
    except ValueError:
        status = OrderStatus.UNKNOWN
    return OrderState(
        symbol=data["symbol"],
        client_order_id=str(data.get("clientOrderId", "")),
        exchange_order_id=str(data["orderId"]) if "orderId" in data else None,
        status=status,
        side=Side(data["side"]),
        type=OrderType(data["type"]) if data.get("type") in OrderType.__members__ else OrderType.LIMIT,
        orig_qty=_D(data.get("origQty", "0")),
        executed_qty=_D(data.get("executedQty", "0")),
        cumulative_quote_qty=_D(data.get("cummulativeQuoteQty", "0")),  # sic — Binance field name
        price=_D(data["price"]) if data.get("price") not in (None, "0.00000000", "0") else None,
        fills=fills,
        updated_at=datetime.now(UTC),
    )


class BinanceSpotAdapter:
    """Spot adapter. Which network it talks to is decided purely by the
    base URLs and credentials injected via Settings (testnet vs live)."""

    def __init__(self, client: BinanceRestClient, ws_base_url: str) -> None:
        self._client = client
        self._ws_base_url = ws_base_url

    # ── public data ──────────────────────────────────────────────────
    async def get_server_time(self) -> datetime:
        data = await self._client.request("GET", "/v3/time", weight=1)
        return datetime.fromtimestamp(int(data["serverTime"]) / 1000, tz=UTC)

    async def get_exchange_rules(self) -> ExchangeRules:
        data = await self._client.request("GET", "/v3/exchangeInfo", weight=20)
        # Apply server-declared rate limits to the client-side limiter.
        limits = {rl["rateLimitType"]: rl for rl in data.get("rateLimits", [])}
        rw = limits.get("REQUEST_WEIGHT", {})
        if rw.get("interval") == "MINUTE":
            self._client.rate_limiter.configure(
                request_weight_per_min=int(rw["limit"]) * int(rw.get("intervalNum", 1))
            )
        symbols = {
            entry["symbol"]: _parse_symbol_rules(entry) for entry in data.get("symbols", [])
        }
        return ExchangeRules(symbols=symbols, fetched_at=datetime.now(UTC))

    async def get_klines(
        self,
        symbol: str,
        interval: str,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> list[Candle]:
        params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": limit}
        if start:
            params["startTime"] = int(start.timestamp() * 1000)
        if end:
            params["endTime"] = int(end.timestamp() * 1000)
        rows = await self._client.request("GET", "/v3/klines", params=params, weight=2)
        return [
            Candle(
                symbol=symbol,
                interval=interval,
                open_time=datetime.fromtimestamp(row[0] / 1000, tz=UTC),
                open=_D(row[1]),
                high=_D(row[2]),
                low=_D(row[3]),
                close=_D(row[4]),
                volume=_D(row[5]),
                quote_volume=_D(row[7]),
                trade_count=int(row[8]),
            )
            for row in rows
        ]

    async def get_order_book(self, symbol: str, limit: int = 20) -> OrderBook:
        data = await self._client.request(
            "GET", "/v3/depth", params={"symbol": symbol, "limit": limit}, weight=5
        )
        return OrderBook(
            symbol=symbol,
            bids=[BookLevel(price=_D(p), qty=_D(q)) for p, q in data["bids"]],
            asks=[BookLevel(price=_D(p), qty=_D(q)) for p, q in data["asks"]],
            fetched_at=datetime.now(UTC),
        )

    # ── account / orders (signed) ────────────────────────────────────
    async def get_account(self) -> AccountState:
        data = await self._client.request("GET", "/v3/account", signed=True, weight=20)
        balances = {
            b["asset"]: Balance(asset=b["asset"], free=_D(b["free"]), locked=_D(b["locked"]))
            for b in data.get("balances", [])
            if _D(b["free"]) != 0 or _D(b["locked"]) != 0
        }
        state = AccountState(
            balances=balances,
            can_trade=bool(data.get("canTrade", False)),
            can_withdraw=bool(data.get("canWithdraw", False)),
            fetched_at=datetime.now(UTC),
        )
        if state.can_withdraw:
            logger.critical(
                "api_key_has_withdraw_permission",
                detail="This key can withdraw funds. Replace it with a restricted key immediately.",
            )
        return state

    async def place_order(self, request: OrderRequest) -> OrderState:
        params: dict[str, Any] = {
            "symbol": request.symbol,
            "side": request.side.value,
            "type": request.type.value,
            "quantity": f"{request.quantity.normalize():f}",
            "newClientOrderId": request.client_order_id,
            "newOrderRespType": "FULL",
        }
        if request.type is OrderType.LIMIT:
            assert request.price is not None
            params["price"] = f"{request.price.normalize():f}"
            params["timeInForce"] = (request.time_in_force or "GTC")
        data = await self._client.request(
            "POST", "/v3/order", params=params, signed=True, weight=1, is_order=True
        )
        state = _parse_order_state(data)
        logger.info(
            "order_placed",
            symbol=state.symbol,
            client_order_id=state.client_order_id,
            status=state.status.value,
        )
        return state

    async def cancel_order(self, symbol: str, client_order_id: str) -> OrderState:
        data = await self._client.request(
            "DELETE",
            "/v3/order",
            params={"symbol": symbol, "origClientOrderId": client_order_id},
            signed=True,
            weight=1,
        )
        return _parse_order_state(data)

    async def query_order(self, symbol: str, client_order_id: str) -> OrderState:
        data = await self._client.request(
            "GET",
            "/v3/order",
            params={"symbol": symbol, "origClientOrderId": client_order_id},
            signed=True,
            weight=4,
        )
        return _parse_order_state(data)

    async def get_open_orders(self, symbol: str | None = None) -> list[OrderState]:
        weight = 6 if symbol else 80
        data = await self._client.request(
            "GET", "/v3/openOrders", params={"symbol": symbol} if symbol else {}, signed=True, weight=weight
        )
        return [_parse_order_state(o) for o in data]

    # ── streaming ────────────────────────────────────────────────────
    def market_stream(
        self,
        symbols: list[str],
        intervals: list[str],
        *,
        include_trades: bool = False,
        include_depth: bool = False,
    ) -> AsyncIterator[MarketEvent]:
        stream = BinanceMarketStream(
            self._ws_base_url, symbols, intervals,
            include_trades=include_trades, include_depth=include_depth,
        )
        return stream.events()

    async def close(self) -> None:
        await self._client.close()

    # ── convenience ──────────────────────────────────────────────────
    async def verify_connectivity(self) -> None:
        """Startup check: ping, time sync, account permissions. Fail closed."""
        await self._client.sync_time()
        account = await self.get_account()
        if not account.can_trade:
            raise ExchangeError("API key cannot trade — failing closed")
