"use client";

import { useEffect, useState } from "react";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const TOKEN = process.env.NEXT_PUBLIC_API_TOKEN ?? "";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}/api/v1${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

interface CostReport {
  equity: number; symbol: string; position_notional: number;
  round_trip_cost_usd: number; round_trip_cost_pct_of_equity: number;
  breakeven_move_pct: number; daily_cost_usd: number;
  monthly_cost_pct_of_equity: number; trades_until_10pct_of_equity_spent: number;
  smallest_valid_notional: number; maker_round_trip_cost_usd: number;
  maker_saving_usd_per_trade: number; maker_saving_pct_per_month: number;
  warnings: string[]; plain_summary: string;
}
interface SizingReport {
  quantity: number; notional: number; risk_amount_usd: number; feasible: boolean;
  blocking_reason: string; min_equity_for_current_settings: number | null;
  workable_risk_per_trade: number | null; max_simultaneous_positions: number;
  notes: string[];
}
interface Summary {
  equity: number; peak_equity: number;
  recovery: { drawdown_pct: number; gain_needed_pct: number; message: string };
  growth: {
    trades_sampled: number; expectancy_pct: number | null;
    statistically_meaningful: boolean; p10_equity: number | null;
    p50_equity: number | null; p90_equity: number | null;
    prob_below_start: number | null; caveats: string[]; message: string;
  };
  divergence: { samples: number; verdict: string; message: string };
  behaviour: { code: string; severity: string; message: string }[];
  guardrails: {
    min_expected_edge_pct: number; max_trades_per_day: number;
    max_positions: number; adjustments: string[]; rationale: string;
  };
  disclaimer: string;
}

export function CostMicroscope({ symbol = "BTCUSDT" }: { symbol?: string }) {
  const [report, setReport] = useState<CostReport | null>(null);
  const [error, setError] = useState("");
  const [tradesPerDay, setTradesPerDay] = useState(3);
  const [bnb, setBnb] = useState(false);

  useEffect(() => {
    req<CostReport>(`/awareness/costs?symbol=${symbol}&trades_per_day=${tradesPerDay}` +
      `&bnb_discount=${bnb ? 0.25 : 0}`)
      .then((r) => { setReport(r); setError(""); })
      .catch((e) => setError(e instanceof Error ? e.message : "failed"));
  }, [symbol, tradesPerDay, bnb]);

  if (error) {
    return <div className="error-banner">Cost microscope unavailable: {error}
      <br /><span style={{ fontSize: 12 }}>Run <code>cryptobot doctor</code> in backend/.</span></div>;
  }
  if (!report) return <p className="empty">Calculating your cost reality…</p>;

  return (
    <div>
      <p style={{ fontSize: 13, lineHeight: 1.6, marginBottom: 12 }}>{report.plain_summary}</p>

      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 8 }}>
        <Stat label="Cost per round trip" value={`$${report.round_trip_cost_usd.toFixed(2)}`}
          sub={`${report.round_trip_cost_pct_of_equity.toFixed(2)}% of equity`} />
        <Stat label="Break-even move needed" value={`${report.breakeven_move_pct.toFixed(2)}%`}
          sub="before any profit" tone="amber" />
        <Stat label="Monthly cost drag" value={`${report.monthly_cost_pct_of_equity.toFixed(1)}%`}
          sub={`at ${tradesPerDay}/day`}
          tone={report.monthly_cost_pct_of_equity >= 10 ? "red" : "normal"} />
        <Stat label="Trades until 10% burned" value={report.trades_until_10pct_of_equity_spent.toFixed(0)}
          sub="on costs alone" />
        <Stat label="Maker saving" value={`$${report.maker_saving_usd_per_trade.toFixed(2)}`}
          sub={`${report.maker_saving_pct_per_month.toFixed(1)}%/month`} tone="green" />
      </div>

      <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 12, flexWrap: "wrap" }}>
        <span className="hint">trades/day:</span>
        {[1, 3, 6, 10].map((n) => (
          <button key={n} className="chip"
            style={n === tradesPerDay ? { borderColor: "var(--accent)", color: "var(--accent)" } : {}}
            onClick={() => setTradesPerDay(n)}>{n}</button>
        ))}
        <button className="chip"
          style={bnb ? { borderColor: "var(--green)", color: "var(--green)" } : {}}
          onClick={() => setBnb(!bnb)}>BNB fee discount {bnb ? "on" : "off"}</button>
      </div>

      {report.warnings.map((w, i) => (
        <p key={i} style={{ fontSize: 12.5, color: "var(--amber)", marginTop: 8, lineHeight: 1.5 }}>
          ⚠ {w}
        </p>
      ))}
    </div>
  );
}

export function SizingCheck({ symbol = "BTCUSDT" }: { symbol?: string }) {
  const [risk, setRisk] = useState(0.5);
  const [stop, setStop] = useState(3);
  const [report, setReport] = useState<SizingReport | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    req<SizingReport>("/awareness/sizing", {
      method: "POST",
      body: JSON.stringify({ symbol, risk_per_trade: risk / 100, stop_distance_pct: stop / 100 }),
    }).then((r) => { setReport(r); setError(""); })
      .catch((e) => setError(e instanceof Error ? e.message : "failed"));
  }, [symbol, risk, stop]);

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
        <label className="hint">Risk per trade: <strong>{risk.toFixed(2)}%</strong>
          <input type="range" min={0.1} max={2} step={0.05} value={risk}
            onChange={(e) => setRisk(Number(e.target.value))}
            style={{ width: "100%", padding: 0, marginTop: 6 }} />
        </label>
        <label className="hint">Stop distance: <strong>{stop.toFixed(1)}%</strong>
          <input type="range" min={0.5} max={10} step={0.5} value={stop}
            onChange={(e) => setStop(Number(e.target.value))}
            style={{ width: "100%", padding: 0, marginTop: 6 }} />
        </label>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {report && (
        <div style={{
          border: `1px solid ${report.feasible ? "var(--green)" : "var(--red)"}`,
          background: report.feasible ? "var(--green-dim)" : "var(--red-dim)",
          borderRadius: 8, padding: "10px 12px", fontSize: 13, lineHeight: 1.6,
        }}>
          <strong style={{ fontWeight: 550 }}>
            {report.feasible ? "✓ These settings can trade" : "✗ The bot could never trade with these settings"}
          </strong>
          <br />
          {report.feasible ? (
            <>
              Position: <span style={{ fontFamily: "var(--mono)" }}>{report.quantity}</span> ≈
              ${report.notional.toFixed(2)} · risking ${report.risk_amount_usd.toFixed(2)} ·
              your account could fund {report.max_simultaneous_positions} such position(s).
              {report.notes.map((n, i) => <span key={i}><br />{n}</span>)}
            </>
          ) : report.blocking_reason}
        </div>
      )}
      <p className="hint" style={{ marginTop: 8 }}>
        Sizes are computed by the backend using live prices and the exchange&apos;s real
        minimums — not estimated in the browser.
      </p>
    </div>
  );
}

export function AwarenessSummary() {
  const [data, setData] = useState<Summary | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    req<Summary>("/awareness/summary")
      .then((d) => { setData(d); setError(""); })
      .catch((e) => setError(e instanceof Error ? e.message : "failed"));
  }, []);

  if (error) return <div className="error-banner">Unavailable: {error}</div>;
  if (!data) return <p className="empty">Loading…</p>;

  return (
    <div style={{ fontSize: 13, lineHeight: 1.6 }}>
      <Section title="Drawdown recovery">
        <p>{data.recovery.message}</p>
        {data.recovery.drawdown_pct > 0 && (
          <p style={{ fontFamily: "var(--mono)", marginTop: 4 }}>
            −{data.recovery.drawdown_pct.toFixed(1)}% → needs +{data.recovery.gain_needed_pct.toFixed(1)}%
          </p>
        )}
      </Section>

      <Section title="What your own results imply (not a forecast)">
        <p>{data.growth.message}</p>
        {data.growth.p50_equity !== null && (
          <div style={{ display: "flex", gap: 12, marginTop: 6, fontFamily: "var(--mono)", fontSize: 12 }}>
            <span className="neg">poor {data.growth.p10_equity?.toFixed(0)}</span>
            <span>middle {data.growth.p50_equity?.toFixed(0)}</span>
            <span className="pos">good {data.growth.p90_equity?.toFixed(0)}</span>
          </div>
        )}
        {data.growth.caveats.map((c, i) => (
          <p key={i} style={{ color: "var(--amber)", fontSize: 12, marginTop: 4 }}>⚠ {c}</p>
        ))}
      </Section>

      <Section title="Are simulated costs realistic?">
        <p>{data.divergence.message}</p>
      </Section>

      <Section title="Small-account guardrails in force">
        <p style={{ fontFamily: "var(--mono)", fontSize: 12 }}>
          min edge {data.guardrails.min_expected_edge_pct.toFixed(3)}% ·
          max {data.guardrails.max_trades_per_day} trades/day ·
          max {data.guardrails.max_positions} positions
        </p>
        {data.guardrails.adjustments.map((a, i) => (
          <p key={i} style={{ color: "var(--text-muted)", fontSize: 12, marginTop: 4 }}>{a}</p>
        ))}
        <p style={{ color: "var(--text-muted)", fontSize: 12, marginTop: 4 }}>
          {data.guardrails.rationale}
        </p>
      </Section>

      <Section title="Behaviour check">
        {data.behaviour.map((b, i) => (
          <p key={i} style={{ color: b.severity === "warning" ? "var(--amber)" : "var(--text-muted)" }}>
            {b.severity === "warning" ? "⚠ " : "· "}{b.message}
          </p>
        ))}
      </Section>

      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <a href={`${BASE}/api/v1/export/fills.csv`} target="_blank" rel="noreferrer">
          <button className="chip">Export fills CSV (tax records)</button>
        </a>
      </div>
      <p className="hint" style={{ marginTop: 8 }}>{data.disclaimer}</p>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ borderTop: "1px solid var(--border)", padding: "10px 0" }}>
      <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>{title}</div>
      {children}
    </div>
  );
}

function Stat({ label, value, sub, tone = "normal" }: {
  label: string; value: string; sub?: string; tone?: "normal" | "green" | "amber" | "red";
}) {
  const color = tone === "green" ? "var(--green)" : tone === "amber" ? "var(--amber)"
    : tone === "red" ? "var(--red)" : "var(--text)";
  return (
    <div style={{ background: "var(--surface-2)", borderRadius: 8, padding: "8px 10px" }}>
      <div style={{ fontSize: 11.5, color: "var(--text-muted)" }}>{label}</div>
      <div style={{ fontSize: 17, fontFamily: "var(--mono)", color, marginTop: 2 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{sub}</div>}
    </div>
  );
}
