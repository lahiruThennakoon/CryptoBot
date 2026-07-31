"use client";

import { useEffect, useState } from "react";
import { api, NoTradeReport } from "@/lib/api";

export function NoTrades() {
  const [report, setReport] = useState<NoTradeReport | null>(null);
  const [hours, setHours] = useState(24);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    const load = () => api.noTrade(hours)
      .then((r) => { if (alive) { setReport(r); setError(""); } })
      .catch((e) => alive && setError(e instanceof Error ? e.message : "failed to load"));
    load();
    const id = setInterval(load, 30_000);
    return () => { alive = false; clearInterval(id); };
  }, [hours]);

  if (error && !report) {
    return <div className="error-banner">Couldn’t load: {error}
      <br /><span style={{ fontSize: 12 }}>Run <code>cryptobot doctor</code> in backend/ for the fix.</span>
    </div>;
  }
  if (!report) return <p className="empty">Loading…</p>;

  return (
    <div>
      <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
        {[24, 72, 168].map((h) => (
          <button key={h} onClick={() => setHours(h)}
            style={h === hours ? { borderColor: "var(--accent)" } : {}}>
            {h === 24 ? "24h" : h === 72 ? "3d" : "7d"}
          </button>
        ))}
        <span style={{ marginLeft: "auto", fontSize: 12, color: "var(--text-muted)", alignSelf: "center" }}>
          {report.trades_executed} traded · {report.signals_skipped} skipped
        </span>
      </div>

      <p style={{ fontSize: 13, color: "var(--text)", marginBottom: 10, lineHeight: 1.5 }}>
        {report.summary}
      </p>

      {report.reasons.map((r) => (
        <div key={r.code} style={{ borderTop: "1px solid var(--border)", padding: "8px 0" }}>
          <button
            onClick={() => setOpen(open === r.code ? null : r.code)}
            style={{ background: "none", border: "none", padding: 0, width: "100%",
                     display: "flex", justifyContent: "space-between", textAlign: "left" }}>
            <span>
              <span style={{ color: r.protective ? "var(--green)" : "var(--amber)", marginRight: 8 }}>
                {r.protective ? "🛡" : "⚠"}
              </span>
              {r.title}
            </span>
            <span style={{ fontFamily: "var(--mono)", color: "var(--text-muted)" }}>×{r.count}</span>
          </button>
          {open === r.code && (
            <p style={{ fontSize: 12, color: "var(--text-muted)", margin: "6px 0 0 24px", lineHeight: 1.5 }}>
              {r.explanation}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
