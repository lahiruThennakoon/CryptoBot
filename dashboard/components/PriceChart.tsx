"use client";

import { useEffect, useState } from "react";
import { api, CandlesResponse } from "@/lib/api";
import { CandleChart } from "@/components/Charts";

const INTERVALS = ["5m", "15m", "1h", "4h"];

export function PriceChart({ symbol, enabledSymbols }: {
  symbol?: string; enabledSymbols: string[];
}) {
  const [active, setActive] = useState(symbol ?? enabledSymbols[0] ?? "BTCUSDT");
  const [interval, setInterval_] = useState("1h");
  const [data, setData] = useState<CandlesResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (symbol) setActive(symbol);
  }, [symbol]);

  useEffect(() => {
    let alive = true;
    setError("");
    api.candles(active, interval, 200)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e instanceof Error ? e.message : "failed to load candles"));
    return () => { alive = false; };
  }, [active, interval]);

  const symbols = enabledSymbols.length ? enabledSymbols : ["BTCUSDT", "ETHUSDT"];
  const last = data?.candles.at(-1);
  const first = data?.candles[0];
  const change = last && first ? ((last.c / first.c - 1) * 100) : null;

  return (
    <div>
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", marginBottom: 10 }}>
        {symbols.map((s) => (
          <button key={s} className="chip"
            style={s === active ? { borderColor: "var(--accent)", color: "var(--accent)" } : {}}
            onClick={() => setActive(s)}>{s}</button>
        ))}
        <span style={{ width: 12 }} />
        {INTERVALS.map((iv) => (
          <button key={iv} className="chip"
            style={iv === interval ? { borderColor: "var(--accent)", color: "var(--accent)" } : {}}
            onClick={() => setInterval_(iv)}>{iv}</button>
        ))}
        {last && (
          <span style={{ marginLeft: "auto", fontFamily: "var(--mono)", fontSize: 13 }}>
            {last.c.toLocaleString(undefined, { maximumFractionDigits: 2 })}
            {change !== null && (
              <span className={change >= 0 ? "pos" : "neg"} style={{ marginLeft: 8, fontSize: 12 }}>
                {change >= 0 ? "+" : ""}{change.toFixed(2)}% over window
              </span>
            )}
          </span>
        )}
      </div>

      {error ? (
        <p className="empty">Couldn’t load candles: {error}</p>
      ) : (
        <CandleChart candles={data?.candles ?? []} symbol={active} />
      )}

      <p className="hint" style={{ marginTop: 6 }}>
        {data ? `${data.count} candles · ${data.source}` : "loading…"} — historical prices from
        Binance, stored locally. Hover for open/high/low/close and volume.
      </p>
    </div>
  );
}
