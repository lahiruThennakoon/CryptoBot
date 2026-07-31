"use client";

import { useEffect, useState } from "react";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const TOKEN = process.env.NEXT_PUBLIC_API_TOKEN ?? "";

interface Rec {
  symbol: string; suitable: boolean; score: number; headline: string;
  affordable: boolean; position_notional: number;
  move_to_cost_ratio: number | null; components: Record<string, number>;
  reasons: string[]; blockers: string[]; already_enabled: boolean;
}
interface RecResponse {
  equity: number; advice: string; recommendations: Rec[]; disclaimer: string;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}/api/v1${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export function PairRecommendations({ onChanged }: { onChanged?: () => void }) {
  const [data, setData] = useState<RecResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    req<RecResponse>("/pairs/recommend?limit=10")
      .then((d) => { setData(d); setError(""); })
      .catch((e) => setError(e instanceof Error ? e.message : "failed"))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const enable = async (symbol: string) => {
    setBusy(symbol);
    try {
      await req(`/pairs/${symbol}/enable`, { method: "POST" });
      load();
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "could not enable");
    } finally { setBusy(""); }
  };

  if (error) {
    return <div className="error-banner">Screening unavailable: {error}
      <br /><span style={{ fontSize: 12 }}>Run <code>cryptobot doctor</code> in backend/.</span>
    </div>;
  }
  if (!data) return <p className="empty">{loading ? "Screening pairs for your account…" : "—"}</p>;

  return (
    <div>
      <p style={{ fontSize: 13, lineHeight: 1.6, marginBottom: 10 }}>{data.advice}</p>
      <button className="chip" onClick={load} disabled={loading} style={{ marginBottom: 10 }}>
        {loading ? "screening…" : "re-screen"}
      </button>

      <table>
        <thead>
          <tr><th>Pair</th><th>Suitability</th><th>Move vs cost</th><th>Position</th><th></th></tr>
        </thead>
        <tbody>
          {data.recommendations.map((r) => (
            <>
              <tr key={r.symbol} style={{ opacity: r.suitable ? 1 : 0.55 }}>
                <td>
                  {r.symbol}
                  {r.already_enabled && <span style={{ color: "var(--green)" }}> ● on</span>}
                </td>
                <td style={{ color: r.suitable ? (r.score >= 0.7 ? "var(--green)" : "var(--text)") : "var(--text-muted)" }}>
                  {r.headline}
                </td>
                <td>{r.move_to_cost_ratio !== null ? `${r.move_to_cost_ratio.toFixed(1)}x` : "—"}</td>
                <td>{r.suitable ? `$${r.position_notional.toFixed(2)}` : "—"}</td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <button className="chip"
                    onClick={() => setExpanded(expanded === r.symbol ? null : r.symbol)}>
                    {expanded === r.symbol ? "▲" : "why"}
                  </button>
                  {r.suitable && !r.already_enabled && (
                    <button className="chip" style={{ marginLeft: 4 }}
                      disabled={busy === r.symbol} onClick={() => enable(r.symbol)}>
                      {busy === r.symbol ? "…" : "enable"}
                    </button>
                  )}
                </td>
              </tr>
              {expanded === r.symbol && (
                <tr key={`${r.symbol}-why`}>
                  <td colSpan={5} style={{ background: "var(--surface-2)", fontFamily: "inherit", fontSize: 12 }}>
                    <div style={{ padding: "6px 2px", lineHeight: 1.6 }}>
                      {r.blockers.map((b, i) => (
                        <div key={i} style={{ color: "var(--red)" }}>✗ {b}</div>
                      ))}
                      {r.reasons.map((x, i) => (
                        <div key={i} style={{ color: "var(--text-muted)" }}>· {x}</div>
                      ))}
                      {Object.keys(r.components).length > 0 && (
                        <div style={{ fontFamily: "var(--mono)", marginTop: 4 }}>
                          {Object.entries(r.components)
                            .map(([k, v]) => `${k} ${v.toFixed(2)}`).join(" · ")}
                        </div>
                      )}
                    </div>
                  </td>
                </tr>
              )}
            </>
          ))}
        </tbody>
      </table>

      <p className="hint" style={{ marginTop: 8 }}>{data.disclaimer}</p>
    </div>
  );
}
