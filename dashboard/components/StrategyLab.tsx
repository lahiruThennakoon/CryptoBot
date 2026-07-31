"use client";

import { useEffect, useState } from "react";
import { api, LabResult, StrategyInfo } from "@/lib/api";

const GRADE_COLORS: Record<string, string> = {
  promising: "var(--green)",
  weak: "var(--amber)",
  inconclusive: "var(--text-muted)",
  no_trades: "var(--text-muted)",
  no_edge: "var(--red)",
};

export function StrategyLab() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [results, setResults] = useState<Record<string, LabResult>>({});
  const [running, setRunning] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.labStrategies().then(setStrategies)
      .catch((e) => setError(e instanceof Error ? e.message : "failed to load strategies"));
  }, []);

  const run = async (name: string) => {
    setRunning(name);
    setError("");
    try {
      const result = await api.labBacktest(name);
      setResults((prev) => ({ ...prev, [name]: result }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "backtest failed");
    } finally {
      setRunning(null);
    }
  };

  const runAll = async () => {
    for (const s of strategies) await run(s.name);
  };

  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 12, alignItems: "center" }}>
        <button className="primary" onClick={runAll} disabled={running !== null || !strategies.length}>
          {running ? `Testing ${running}…` : "Test all strategies on your imported history"}
        </button>
        <span className="hint">runs a full backtest per strategy — a few seconds each</span>
      </div>

      {error && (
        <div className="error-banner">
          {error}
          <br /><span style={{ fontSize: 12 }}>
            409 means no candles are stored yet — run
            {" "}<code>cryptobot import-history --symbol BTCUSDT --interval 1h --days 730</code>.
            Any other error: run <code>cryptobot doctor</code>.
          </span>
        </div>
      )}
      {!strategies.length && !error && <p className="empty">Loading strategies…</p>}

      <table>
        <thead>
          <tr>
            <th>Strategy</th><th>Verdict</th><th>Net</th><th>Holding</th>
            <th>Trades</th><th>Max DD</th><th></th>
          </tr>
        </thead>
        <tbody>
          {strategies.map((s) => {
            const r = results[s.name];
            return (
              <tr key={s.name}>
                <td>
                  {s.name}
                  <br />
                  <span style={{ color: "var(--text-muted)", fontSize: 11, fontFamily: "inherit" }}>
                    {s.required_conditions}
                  </span>
                </td>
                <td style={{ maxWidth: 260, fontFamily: "inherit" }}>
                  {r ? (
                    <span style={{ color: GRADE_COLORS[r.verdict.grade] ?? "var(--text)" }}>
                      {r.verdict.headline}
                    </span>
                  ) : (
                    <span style={{ color: "var(--text-muted)" }}>not tested yet</span>
                  )}
                </td>
                <td className={r && r.metrics.net_return_pct >= 0 ? "pos" : "neg"}>
                  {r ? `${r.metrics.net_return_pct.toFixed(2)}%` : "—"}
                </td>
                <td>{r ? `${r.metrics.buy_hold_return_pct.toFixed(2)}%` : "—"}</td>
                <td>{r ? r.metrics.n_trades : "—"}</td>
                <td>{r ? `${r.metrics.max_drawdown_pct.toFixed(1)}%` : "—"}</td>
                <td>
                  <button disabled={running !== null} onClick={() => run(s.name)}>
                    {running === s.name ? "…" : "Test"}
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {Object.values(results).length > 0 && (
        <div style={{ marginTop: 12 }}>
          {Object.values(results).map((r) => (
            <details key={r.strategy} style={{ marginBottom: 8, fontSize: 13 }}>
              <summary style={{ cursor: "pointer", color: "var(--text-muted)" }}>
                {r.strategy}: {r.verdict.headline} — details
              </summary>
              <p style={{ margin: "6px 0", lineHeight: 1.5 }}>{r.verdict.detail}</p>
              <p style={{ color: "var(--text-muted)", fontSize: 12 }}>
                {r.bars.toLocaleString()} candles ({new Date(r.period.from).toLocaleDateString()}
                {" → "}{new Date(r.period.to).toLocaleDateString()}) ·
                fees paid {r.metrics.total_fees.toFixed(2)} ·
                win rate {r.metrics.win_rate?.toFixed(0) ?? "—"}% ·
                in market {r.metrics.exposure_time_pct.toFixed(1)}% of the time
              </p>
              {Object.keys(r.rejections).length > 0 && (
                <p style={{ color: "var(--text-muted)", fontSize: 12 }}>
                  Skipped signals: {Object.entries(r.rejections)
                    .map(([code, count]) => `${code}×${count}`).join(", ")}
                </p>
              )}
              <p style={{ color: "var(--text-muted)", fontSize: 11 }}>{r.note}</p>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}
