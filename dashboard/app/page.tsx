"use client";

import { useCallback, useEffect, useState } from "react";
import {
  api, Overview, EquityPoint, Position, Fill, SignalEntry,
} from "@/lib/api";
import { EquityChart } from "@/components/EquityChart";
import { Controls } from "@/components/Controls";
import { RiskBars } from "@/components/RiskBars";
import { NoTrades } from "@/components/NoTrades";
import { Graduation } from "@/components/Graduation";
import { StrategyLab } from "@/components/StrategyLab";
import { TradingPairs } from "@/components/TradingPairs";
import { ChatPanel } from "@/components/ChatPanel";
import { SessionSettings } from "@/components/SessionSettings";
import { PriceChart } from "@/components/PriceChart";
import { BarChart } from "@/components/Charts";
import { DailyPerformance } from "@/lib/api";
import { AwarenessSummary, CostMicroscope, SizingCheck } from "@/components/Awareness";
import { PairRecommendations } from "@/components/PairRecommendations";

const POLL_MS = 5000;
type Tab = "overview" | "pairs" | "reality" | "lab" | "assistant" | "settings";

export default function Dashboard() {
  const [tab, setTab] = useState<Tab>("overview");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [equity, setEquity] = useState<EquityPoint[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [fills, setFills] = useState<Fill[]>([]);
  const [signals, setSignals] = useState<SignalEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [askSeed, setAskSeed] = useState<string | null>(null);
  const [daily, setDaily] = useState<DailyPerformance | null>(null);
  const [enabledPairs, setEnabledPairs] = useState<string[]>([]);

  const refresh = useCallback(async () => {
    try {
      const [o, e, p, f, s] = await Promise.all([
        api.overview(), api.equity(), api.positions(), api.fills(), api.signals(),
      ]);
      setOverview(o); setEquity(e); setPositions(p); setFills(f); setSignals(s);
      setError(null);
      api.dailyPerformance().then(setDaily).catch(() => {});
      api.pairs().then((ps) => setEnabledPairs(ps.filter((x) => x.enabled).map((x) => x.symbol)))
        .catch(() => {});
    } catch (err) {
      setError(err instanceof Error ? err.message : "connection failed");
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  const askAI = (question: string) => {
    setAskSeed(question);
    setTab("assistant");
  };

  const startEquity = equity.length ? equity[0].equity : null;
  const nowEquity = overview?.equity ?? null;
  const pnl = startEquity !== null && nowEquity !== null ? nowEquity - startEquity : null;
  const executionMode =
    (overview as unknown as { execution_mode?: string })?.execution_mode ?? overview?.mode;

  return (
    <main>
      <div className="topbar">
        <div className="topbar-row">
          <span className="brand">CryptoBot<small>risk-first trading</small></span>
          {overview && (
            <>
              <span className="badge paper">{executionMode} mode</span>
              <span className="badge muted">live trading {overview.live_trading}</span>
              {overview.emergency_stop ? (
                <span className="badge danger">EMERGENCY STOP</span>
              ) : overview.paused ? (
                <span className="badge danger">paused</span>
              ) : (
                <span className="badge ok">running</span>
              )}
            </>
          )}
          <div style={{ marginLeft: "auto" }}>
            <Controls overview={overview} onAction={refresh} />
          </div>
        </div>
        <nav className="tabs" aria-label="Sections">
          {([["overview", "Overview"], ["pairs", "Trading pairs"],
             ["reality", "Cost reality"], ["lab", "Strategy lab"],
             ["assistant", "AI assistant"], ["settings", "Settings"]] as [Tab, string][]).map(
            ([key, label]) => (
              <button key={key} className={`tab ${tab === key ? "active" : ""}`}
                onClick={() => setTab(key)}>{label}</button>
            ),
          )}
        </nav>
      </div>

      {error && <div className="error-banner">API unreachable: {error}</div>}

      {tab === "overview" && (
        <>
          <div className="grid kpis" style={{ marginBottom: 12 }}>
            <Kpi label="Equity (USDT)" value={fmt(nowEquity)} />
            <Kpi label="PnL (7d window)" value={fmt(pnl, true)}
                 cls={pnl == null ? "" : pnl >= 0 ? "pos" : "neg"} />
            <Kpi label="Cash" value={fmt(overview?.cash ?? null)} />
            <Kpi label="Exposure" value={fmt(overview?.exposure ?? null)} />
            <Kpi label="Open positions" value={overview ? String(overview.open_positions) : "—"} />
          </div>

          <section className="card" style={{ marginBottom: 12 }}>
            <h2>Price — enabled pairs</h2>
            <PriceChart enabledSymbols={enabledPairs} />
          </section>

          <div className="grid two-col">
            <div className="grid" style={{ gap: 12 }}>
              <section className="card">
                <h2>Equity — last 7 days</h2>
                <EquityChart points={equity} />
              </section>
              <section className="card">
                <h2>Daily result after fees</h2>
                <BarChart bars={(daily?.days ?? []).map((d) => ({
                  label: d.date, value: d.net_pnl,
                  extra: `${d.trades} trade(s) · fees ${d.fees.toFixed(2)}`,
                }))} />
                <p className="hint" style={{ marginTop: 6 }}>
                  {daily?.note ?? "Net of all fees."} Values are simulated (paper trading).
                </p>
              </section>
              <section className="card">
                <h2>Open positions</h2>
                <PositionsTable rows={positions} onAsk={askAI} />
              </section>
              <section className="card">
                <h2>Recent fills</h2>
                <FillsTable rows={fills} />
              </section>
            </div>
            <div className="grid" style={{ gap: 12 }}>
              <section className="card">
                <h2>Why didn’t it trade?</h2>
                <NoTrades />
              </section>
              <section className="card">
                <h2>Risk-limit utilization</h2>
                <RiskBars overview={overview} equityWindow={equity} />
              </section>
              <section className="card">
                <h2>Road to live trading</h2>
                <Graduation />
              </section>
              <section className="card">
                <h2>Signal log</h2>
                <SignalsLog rows={signals} onAsk={askAI} />
              </section>
            </div>
          </div>
        </>
      )}

      {tab === "pairs" && (
        <div className="grid" style={{ gap: 12 }}>
          <section className="card">
            <h2>Suitable for your account — screened, not predicted</h2>
            <PairRecommendations onChanged={refresh} />
          </section>
          <section className="card">
            <h2>Trading pairs — the bot only trades what you switch on</h2>
            <TradingPairs positions={positions} onAsk={askAI} />
          </section>
          <section className="card">
            <h2>Price chart</h2>
            <PriceChart enabledSymbols={enabledPairs} />
          </section>
        </div>
      )}

      {tab === "reality" && (
        <div className="grid" style={{ gap: 12 }}>
          <section className="card">
            <h2>Cost microscope — what trading actually costs you</h2>
            <CostMicroscope symbol={enabledPairs[0] ?? "BTCUSDT"} />
          </section>
          <div className="grid two-col">
            <section className="card">
              <h2>Sizing reality check</h2>
              <SizingCheck symbol={enabledPairs[0] ?? "BTCUSDT"} />
            </section>
            <section className="card">
              <h2>Awareness</h2>
              <AwarenessSummary />
            </section>
          </div>
        </div>
      )}

      {tab === "lab" && (
        <section className="card">
          <h2>Strategy lab — test ideas on history before trusting them</h2>
          <StrategyLab />
        </section>
      )}

      {tab === "assistant" && (
        <section className="card" style={{ maxWidth: 760, margin: "0 auto" }}>
          <h2>AI assistant</h2>
          <ChatPanel seed={askSeed} onSeedConsumed={() => setAskSeed(null)} />
        </section>
      )}

      {tab === "settings" && (
        <section className="card">
          <h2>Trading session</h2>
          <SessionSettings />
        </section>
      )}

      <p className="disclaimer">
        {overview?.disclaimer ?? "Trading is risky. No profit is guaranteed. Losses are possible."}
        {" "}Historical and simulated performance do not guarantee future results. Signal statuses
        are decision support, not financial advice. Live-money trading is disabled.
      </p>
    </main>
  );
}

function Kpi({ label, value, cls = "" }: { label: string; value: string; cls?: string }) {
  return (
    <div className="card" style={{ padding: "12px 16px" }}>
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value ${cls}`}>{value}</div>
    </div>
  );
}

function fmt(v: number | null, signed = false): string {
  if (v === null || v === undefined) return "—";
  const s = v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return signed && v > 0 ? `+${s}` : s;
}

function PositionsTable({ rows, onAsk }: { rows: Position[]; onAsk: (q: string) => void }) {
  if (!rows.length) {
    return <p className="empty">Flat — no open positions. “No trade” is a valid decision.</p>;
  }
  return (
    <table>
      <thead><tr><th>Symbol</th><th>Qty</th><th>Entry</th><th>Stop</th><th>TP</th><th>Strategy</th><th></th></tr></thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            <td>{r.symbol}</td><td>{r.qty}</td><td>{r.entry}</td>
            <td>{r.stop ?? "—"}</td><td>{r.take_profit ?? "—"}</td><td>{r.strategy}</td>
            <td><button className="chip" onClick={() =>
              onAsk(`Summarise my open ${r.symbol} position and its current risk.`)}>ask AI</button></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function FillsTable({ rows }: { rows: Fill[] }) {
  if (!rows.length) return <p className="empty">No fills yet.</p>;
  return (
    <table>
      <thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Role</th><th>Price</th><th>Qty</th><th>Fee</th></tr></thead>
      <tbody>
        {rows.slice(0, 12).map((r, i) => (
          <tr key={i}>
            <td>{new Date(r.at).toLocaleTimeString()}</td>
            <td>{r.symbol}</td>
            <td className={r.side === "BUY" ? "pos" : "neg"}>{r.side}</td>
            <td>{r.role}</td><td>{r.price}</td><td>{r.qty}</td><td>{r.fee}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function SignalsLog({ rows, onAsk }: { rows: SignalEntry[]; onAsk: (q: string) => void }) {
  if (!rows.length) return <p className="empty">No signals yet — they appear as candles close.</p>;
  return (
    <div style={{ maxHeight: 380, overflowY: "auto" }}>
      <table>
        <thead><tr><th>Time</th><th>Strategy</th><th>Outcome</th><th></th></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td>{new Date(r.at).toLocaleTimeString()}</td>
              <td>{r.strategy}<br /><span style={{ color: "var(--text-muted)" }}>{r.symbol}</span></td>
              <td className={r.outcome === "executed" ? "pos" : ""}>
                {r.outcome}{r.rejection_code ? `: ${r.rejection_code}` : ""}
              </td>
              <td>
                {r.rejection_code && (
                  <button className="chip" onClick={() =>
                    onAsk(`Why was the ${r.strategy} signal on ${r.symbol} rejected with code ${r.rejection_code}?`)}>
                    why?
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
