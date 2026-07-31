"use client";

import { useEffect, useState } from "react";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const TOKEN = process.env.NEXT_PUBLIC_API_TOKEN ?? "";
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

interface SessionCfg {
  session_start_utc: string;
  session_end_utc: string;
  trading_days: number[];
  overnight_policy: string;
  daily_profit_target_pct: number | null;
  target_protection: string;
}

async function req(path: string, init?: RequestInit) {
  const res = await fetch(`${BASE}/api/v1${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw body;
  return body;
}

export function SessionSettings() {
  const [cfg, setCfg] = useState<SessionCfg | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    req("/session").then(setCfg).catch((e) =>
      setLoadError(typeof e?.detail === "string" ? e.detail : "could not load session settings"));
  }, []);

  if (loadError) {
    return <div className="error-banner">{loadError}
      <br /><span style={{ fontSize: 12 }}>
        The session_configs table is probably missing. In backend/:
        {" "}<code>alembic revision --autogenerate -m &quot;v2 tables&quot;</code> →
        {" "}<code>alembic upgrade head</code> → restart uvicorn.
      </span>
    </div>;
  }
  if (!cfg) return <p className="empty">Loading session settings…</p>;

  const set = (patch: Partial<SessionCfg>) => {
    setCfg({ ...cfg, ...patch });
    setSaved(false);
  };

  const save = async () => {
    setBusy(true); setProblems([]); setSaved(false);
    try {
      await req("/session", { method: "PUT", body: JSON.stringify(cfg) });
      setSaved(true);
    } catch (err) {
      const detail = (err as { detail?: { problems?: string[] } })?.detail;
      setProblems(detail?.problems ?? ["Save failed — check the API is running."]);
    } finally { setBusy(false); }
  };

  return (
    <div style={{ maxWidth: 560 }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <label className="hint">Session start (UTC)
          <input value={cfg.session_start_utc} style={{ width: "100%", marginTop: 4 }}
            onChange={(e) => set({ session_start_utc: e.target.value })} placeholder="00:00" />
        </label>
        <label className="hint">Session end (UTC)
          <input value={cfg.session_end_utc} style={{ width: "100%", marginTop: 4 }}
            onChange={(e) => set({ session_end_utc: e.target.value })} placeholder="23:59" />
        </label>
      </div>

      <p className="hint" style={{ margin: "12px 0 4px" }}>Trading days</p>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {DAYS.map((d, i) => {
          const on = cfg.trading_days.includes(i);
          return (
            <button key={d} className="chip"
              style={on ? { borderColor: "var(--green)", color: "var(--green)" } : {}}
              onClick={() => set({
                trading_days: on ? cfg.trading_days.filter((x) => x !== i)
                                 : [...cfg.trading_days, i].sort(),
              })}>{d}</button>
          );
        })}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 14 }}>
        <label className="hint">Overnight positions
          <select value={cfg.overnight_policy} style={{ width: "100%", marginTop: 4 }}
            onChange={(e) => set({ overnight_policy: e.target.value })}>
            <option value="hold">Hold overnight</option>
            <option value="close_at_session_end">Close at session end</option>
          </select>
        </label>
        <label className="hint">Daily profit target (%) — optional
          <input type="number" step="0.1" min="0" style={{ width: "100%", marginTop: 4 }}
            value={cfg.daily_profit_target_pct !== null ? cfg.daily_profit_target_pct * 100 : ""}
            placeholder="none"
            onChange={(e) => set({
              daily_profit_target_pct: e.target.value === "" ? null : Number(e.target.value) / 100,
            })} />
        </label>
      </div>

      {cfg.daily_profit_target_pct !== null && (
        <label className="hint" style={{ display: "block", marginTop: 12 }}>
          When the daily target is reached
          <select value={cfg.target_protection} style={{ width: "100%", marginTop: 4 }}
            onChange={(e) => set({ target_protection: e.target.value })}>
            <option value="stop_trading">Stop new trades for the day (recommended)</option>
            <option value="reduce_size">Continue with half-size positions</option>
            <option value="raise_confidence">Continue, higher confidence required</option>
            <option value="exceptional_only">Only exceptionally strong signals</option>
          </select>
        </label>
      )}

      {problems.length > 0 && (
        <div className="error-banner" style={{ marginTop: 12 }}>
          <strong style={{ fontWeight: 550 }}>Rejected as unsafe or contradictory:</strong>
          <ul style={{ paddingLeft: 18, marginTop: 4 }}>
            {problems.map((p, i) => <li key={i}>{p}</li>)}
          </ul>
        </div>
      )}

      <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 14 }}>
        <button className="primary" onClick={save} disabled={busy}>
          {busy ? "Validating…" : "Save session settings"}
        </button>
        {saved && <span style={{ color: "var(--green)", fontSize: 13 }}>✓ saved</span>}
      </div>
      <p className="hint" style={{ marginTop: 10 }}>
        Settings are validated server-side; combinations that pressure the bot into
        unprofitable behaviour (e.g. targets below trading costs) are rejected.
        Protective stops and exits stay active outside session hours.
      </p>
    </div>
  );
}
