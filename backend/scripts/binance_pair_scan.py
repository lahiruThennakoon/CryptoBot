"""One-off Binance public API scan for pair liquidity and spreads (no credentials)."""
from __future__ import annotations

import json
import urllib.request

QUOTES = ("USDT", "FDUSD", "USDC")
STABLE_BASES = frozenset({"USDT", "USDC", "FDUSD", "BUSD", "TUSD", "DAI"})
MAJORS = frozenset({"BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "LINK", "AVAX", "LTC"})


def get(url: str) -> dict | list:
    with urllib.request.urlopen(url, timeout=20) as resp:
        return json.loads(resp.read())


def main() -> None:
    tickers = get("https://api.binance.com/api/v3/ticker/24hr")
    info = get("https://api.binance.com/api/v3/exchangeInfo")
    trading = {
        s["symbol"]
        for s in info["symbols"]
        if s["status"] == "TRADING" and s.get("isSpotTradingAllowed", True)
    }

    rows: list[dict] = []
    for t in tickers:
        sym = t["symbol"]
        if sym not in trading:
            continue
        for q in QUOTES:
            if sym.endswith(q) and len(sym) > len(q):
                base = sym[: -len(q)]
                if base in STABLE_BASES:
                    continue
                rows.append(
                    {
                        "symbol": sym,
                        "quote": q,
                        "base": base,
                        "vol_usd": float(t["quoteVolume"]),
                        "change_pct": float(t["priceChangePercent"]),
                    }
                )
                break

    rows.sort(key=lambda x: -x["vol_usd"])

    print("=== TOP 15 BY 24h QUOTE VOLUME (live Binance) ===")
    for r in rows[:15]:
        print(f"{r['symbol']:14} vol=${r['vol_usd'] / 1e6:,.0f}M  chg={r['change_pct']:+.2f}%")

    print("\n=== FDUSD PAIRS (top 10 by volume) ===")
    fd = [r for r in rows if r["quote"] == "FDUSD"]
    for r in fd[:10]:
        print(f"{r['symbol']:14} vol=${r['vol_usd'] / 1e6:,.0f}M")

    print("\n=== RECOMMENDED CORE (USDT, vol > 100M, major bases) ===")
    rec = [r for r in rows if r["quote"] == "USDT" and r["base"] in MAJORS and r["vol_usd"] > 100e6]
    for r in rec[:8]:
        print(f"  {r['symbol']}")

    book = get("https://api.binance.com/api/v3/ticker/bookTicker")
    book_map = {b["symbol"]: b for b in book}
    check = [
        "BTCUSDT", "ETHUSDT", "BTCFDUSD", "ETHFDUSD", "SOLUSDT", "SOLFDUSD", "BNBUSDT",
    ]
    print("\n=== SPREAD SNAPSHOT (bookTicker) ===")
    for sym in check:
        b = book_map.get(sym)
        if not b:
            print(f"{sym}: not listed")
            continue
        bid, ask = float(b["bidPrice"]), float(b["askPrice"])
        mid = (bid + ask) / 2
        spread_bps = (ask - bid) / mid * 10000 if mid else 0
        print(f"{sym:12} spread={spread_bps:.2f} bps  bid={bid} ask={ask}")


if __name__ == "__main__":
    main()
