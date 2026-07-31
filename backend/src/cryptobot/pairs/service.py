"""Pair catalog I/O: fetch venue exchangeInfo + live 24h stats, merge with
user settings. Enable/disable is server-validated against selectability."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from cryptobot.core.logging import get_logger
from cryptobot.db.models import PairSettingRow, utcnow
from cryptobot.exchange.binance.client import BinanceRestClient
from cryptobot.pairs.catalog import PairListing, evaluate_pair, parse_24h_ticker

logger = get_logger(__name__)


class PairCatalogService:
    def __init__(self, venue_client: BinanceRestClient, stats_client: BinanceRestClient) -> None:
        self._venue = venue_client        # active venue: tradability
        self._stats = stats_client        # live public REST: real market stats

    async def list_pairs(self, sessions: Any, search: str = "") -> list[PairListing]:
        info = await self._venue.request("GET", "/v3/exchangeInfo", weight=20)
        tickers = await self._stats.request("GET", "/v3/ticker/24hr", weight=80)
        stats_by_symbol = {t["symbol"]: parse_24h_ticker(t) for t in tickers}

        async with sessions() as session:
            settings_rows = (await session.execute(select(PairSettingRow))).scalars().all()
        enabled = {r.symbol for r in settings_rows if r.enabled}

        listings: list[PairListing] = []
        needle = search.upper()
        for entry in info.get("symbols", []):
            symbol = entry["symbol"]
            if needle and needle not in symbol:
                continue
            from cryptobot.pairs.catalog import PairStats

            listing = evaluate_pair(
                symbol=symbol,
                base_asset=entry["baseAsset"],
                quote_asset=entry["quoteAsset"],
                status=entry["status"],
                stats=stats_by_symbol.get(symbol, PairStats(symbol=symbol)),
                is_spot_allowed=bool(entry.get("isSpotTradingAllowed", True)),
            )
            listing.enabled = symbol in enabled
            listings.append(listing)

        # enabled first, then by 24h volume
        listings.sort(key=lambda p: (not p.enabled, -float(p.stats.quote_volume_24h)))
        return listings

    async def set_enabled(self, sessions: Any, symbol: str, enabled: bool) -> PairListing:
        """Server-side validation: refuses to enable non-selectable pairs."""
        listings = await self.list_pairs(sessions, search=symbol)
        listing = next((p for p in listings if p.symbol == symbol), None)
        if listing is None:
            raise LookupError(f"{symbol} is not a known pair on the active venue")
        if enabled and not listing.selectable:
            raise PermissionError(
                f"{symbol} cannot be enabled: {listing.not_selectable_reason}"
            )
        async with sessions() as session:
            row = await session.get(PairSettingRow, symbol)
            if row is None:
                row = PairSettingRow(symbol=symbol)
                session.add(row)
            row.enabled = enabled
            row.updated_at = utcnow()
            await session.commit()
        listing.enabled = enabled
        logger.info("pair_toggled", symbol=symbol, enabled=enabled,
                    warnings=len(listing.warnings))
        return listing


async def enabled_symbols(sessions: Any) -> set[str]:
    """The single source of truth the runtime consults every cycle."""
    async with sessions() as session:
        rows = (await session.execute(
            select(PairSettingRow.symbol).where(PairSettingRow.enabled)
        )).scalars().all()
    return set(rows)


async def ensure_default_pairs(sessions: Any, defaults: list[str]) -> None:
    """Seed BTCUSDT/ETHUSDT as enabled testnet examples on first run only."""
    async with sessions() as session:
        existing = (await session.execute(select(PairSettingRow))).scalars().first()
        if existing is not None:
            return
        for symbol in defaults:
            session.add(PairSettingRow(symbol=symbol, enabled=True, updated_by="default_seed"))
        await session.commit()
