"use client";

import { useEffect, useMemo, useState } from "react";
import { api, Decision, PairInfo, Position } from "@/lib/api";

const STATUS_LABEL: Record<string, { text: string; color: string }> = {
  strong_buy: { text: "Strong Buy", color: "var(--green)" },
  buy: { text: "Buy", color: "var(--green)" },
  hold: { text: "Hold", color: "var(--text-muted)" },
  sell: { text: "Sell", color: "var(--amber)" },
  strong_sell: { text: "Strong Sell", color: "var(--red)" },
  no_trade: { text: "No Trade", color: "var(--text-muted)" },
  risk_blocked: { text: "Risk Blocked", color: "var(--amber)" },
  data_unavailable: { text: "Data Unavailable", color: "var(--text-muted)" },
};

export function TradingPairs({ positions, onAsk }: {
  positions: Position[]; onAsk?: (q: string) => void;
}) {
  const [pairs, setPairs] = useState<PairInfo[]>([]);
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [search, setSearch] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [confirmEnable, setConfirmEnable] = useState<PairInfo | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const refresh = () => {
    api.pairs(search)
      .then((p) => { setPairs(p); setError(""); })
      .catch((e) => setError(e instanceof Error ? e.message : "failed to load pairs"))
      .finally(() => setLoading(false));
    api.currentDecisions()
      .then((ds) => setDecisions(Object.fromEntries(ds.map((d) => [d.symbol, d]))))
      .catch(() => {});   // decisions are optional context, not the main payload
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 15_000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const toggle = async (pair: PairInfo) => {
    if (!pair.enabled && pair.warnings.length > 0) {
      setConfirmEnable(pair);
      return;
    }
    await doToggle(pair);
  };

  const doToggle = async (pair: PairInfo) => {
    setBusy(pair.symbol);
    try {
      if (pair.enabled) await api.disablePair(pair.symbol);
      else await api.enablePair(pair.symbol);
      setError("");
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : `could not toggle ${pair.symbol}`);
    } finally {
      setBusy("");
      setConfirmEnable(null);
    }
  };

  const visible = useMemo(
    () => pairs.filter((p) => showAll || p.enabled || search).slice(0, 30),
    [pairs, showAll, search],
  );
  const positionBySymbol = Object.fromEntries(positions.map((p) => [p.symbol, p]));

  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search pairs (e.g. SOL)…"
          style={{ background: "var(--surface-2)", border: "1px solid var(--border)",
                   borderRadius: 8, padding: "8px 12px", color: "var(--text)", flex: 1 }}
        />
        <button onClick={() => setShowAll(!showAll)}>
          {showAll ? "Show enabled" : "Show all"}
        </button>
      </div>

      {error && (
        <div className="error-banner">
          Couldn’t load pairs: {error}
          <br /><span style={{ fontSize: 12 }}>
            Most likely the new database tables are missing. Run in backend/:
            {" "}<code>alembic revision --autogenerate -m &quot;v2 tables&quot;</code> →
            {" "}<code>alembic upgrade head</code> → restart uvicorn.
            Or run <code>cryptobot doctor</code> for a full diagnosis.
          </span>
        </div>
      )}
      {loading && !pairs.length && <p className="empty">Loading pairs from Binance…</p>}

      <table>
        <thead>
          <tr>
            <th>On</th><th>Pair</th><th>Price</th><th>24h</th><th>Signal</th>
            <th>Spread</th><th>Volume 24h</th><th>Position</th><th></th>
          </tr>
        </thead>
        <tbody>
          {visible.map((p) => {
            const d = decisions[p.symbol];
            const pos = positionBySymbol[p.symbol];
            const status = d ? STATUS_LABEL[d.status] ?? STATUS_LABEL.no_trade : null;
            return (
              <PairRow key={p.symbol} p={p} d={d} pos={pos} status={status}
                busy={busy === p.symbol} expanded={expanded === p.symbol}
                onToggle={() => toggle(p)} onAsk={onAsk}
                onExpand={() => setExpanded(expanded === p.symbol ? null : p.symbol)} />
            );
          })}
        </tbody>
      </table>

      <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 8 }}>
        Signal statuses are decision support, not financial advice. The bot only ever
        trades pairs you switch on, and skips trading whenever any safety check fails.
      </p>

      {confirmEnable && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", zIndex: 50,
                      display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div className="card" style={{ maxWidth: 460 }}>
            <h2>Enable {confirmEnable.symbol}?</h2>
            <p style={{ fontSize: 13, color: "var(--amber)", margin: "8px 0" }}>
              Before you enable this pair, be aware:
            </p>
            <ul style={{ fontSize: 13, color: "var(--text)", paddingLeft: 18 }}>
              {confirmEnable.warnings.map((w, i) => <li key={i} style={{ marginBottom: 6 }}>{w}</li>)}
            </ul>
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 12 }}>
              <button onClick={() => setConfirmEnable(null)}>Cancel</button>
              <button className="danger" onClick={() => doToggle(confirmEnable)}>
                Enable anyway
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function PairRow({ p, d, pos, status, busy, expanded, onToggle, onExpand, onAsk }: {
  p: PairInfo; d?: Decision; pos?: Position;
  status: { text: string; color: string } | null;
  busy: boolean; expanded: boolean; onToggle: () => void; onExpand: () => void;
  onAsk?: (q: string) => void;
}) {
  const reasons: string[] = d ? (Array.isArray(d.reasons) ? d.reasons : d.reasons.list ?? []) : [];
  return (
    <>
      <tr style={{ opacity: p.selectable ? 1 : 0.45 }}>
        <td>
          <button onClick={onToggle} disabled={busy || (!p.enabled && !p.selectable)}
            title={p.selectable ? "" : p.not_selectable_reason}
            style={{ padding: "2px 10px",
                     borderColor: p.enabled ? "var(--green)" : "var(--border)",
                     color: p.enabled ? "var(--green)" : "var(--text-muted)" }}>
            {p.enabled ? "ON" : "off"}
          </button>
        </td>
        <td>
          {p.symbol}
          {p.warnings.length > 0 && <span title={p.warnings.join("\n")} style={{ color: "var(--amber)" }}> ⚠</span>}
          <br /><span style={{ color: "var(--text-muted)", fontSize: 11 }}>{p.base_asset}/{p.quote_asset}</span>
        </td>
        <td>{p.last_price.toLocaleString(undefined, { maximumFractionDigits: 4 })}</td>
        <td className={p.price_change_pct_24h >= 0 ? "pos" : "neg"}>
          {p.price_change_pct_24h >= 0 ? "+" : ""}{p.price_change_pct_24h.toFixed(1)}%
        </td>
        <td>
          {status && d ? (
            <span style={{ color: status.color }}>
              {status.text} <span style={{ color: "var(--text-muted)" }}>{d.confidence.toFixed(2)}</span>
            </span>
          ) : <span style={{ color: "var(--text-muted)" }}>—</span>}
        </td>
        <td>{p.spread_pct.toFixed(3)}%</td>
        <td>${(p.quote_volume_24h / 1e6).toFixed(0)}M</td>
        <td>
          {pos ? (
            <span>{pos.qty} @ {Number(pos.entry).toLocaleString()}</span>
          ) : <span style={{ color: "var(--text-muted)" }}>flat</span>}
        </td>
        <td style={{ whiteSpace: "nowrap" }}>
          {d && <button className="chip" onClick={onExpand}>{expanded ? "▲" : "why?"}</button>}
          {onAsk && (
            <button className="chip" style={{ marginLeft: 4 }}
              onClick={() => onAsk(`Explain the current ${p.symbol} signal in simple terms.`)}>
              ask AI
            </button>
          )}
        </td>
      </tr>
      {expanded && d && (
        <tr>
          <td colSpan={9} style={{ background: "var(--surface-2)", fontFamily: "inherit", fontSize: 12 }}>
            <div style={{ padding: "6px 4px", lineHeight: 1.6 }}>
              <strong style={{ fontWeight: 500 }}>Score {d.score.toFixed(2)}</strong> ·
              analysed {new Date(d.at).toLocaleTimeString()} ·
              {" "}est. entry {d.entry_estimate?.toFixed(2) ?? "—"} ·
              stop {d.stop_price?.toFixed(2) ?? "—"} · target {d.take_profit?.toFixed(2) ?? "—"} ·
              est. costs {( (d.est_fees + d.est_spread + d.est_slippage) * 100).toFixed(2)}% ·
              expected net {d.expected_net_return !== null ? `${(d.expected_net_return * 100).toFixed(2)}%` : "—"}
              <br />
              Supporting: {Object.entries(d.supporting).map(([k, v]) => `${k} ${v >= 0 ? "+" : ""}${v}`).join(", ") || "none"}
              <br />
              Conflicting: {Object.entries(d.conflicting).map(([k, v]) => `${k} ${v}`).join(", ") || "none"}
              {reasons.length > 0 && (<><br />Reasons: {reasons.join(" ")}</>)}
              <br /><span style={{ color: "var(--text-muted)" }}>{d.advice_disclaimer}</span>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
