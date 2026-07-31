"use client";

import { useEffect, useState } from "react";
import { api, GraduationReport } from "@/lib/api";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const TOKEN = process.env.NEXT_PUBLIC_API_TOKEN ?? "";

interface ManualItem {
  name: string; label: string; done: boolean; manual: boolean;
  why?: string; how?: string[]; pass_criteria?: string;
  notes?: string; acknowledged_by?: string; acknowledged_at?: string | null;
}

export function Graduation() {
  const [report, setReport] = useState<GraduationReport | null>(null);
  const [error, setError] = useState("");
  const [openDrill, setOpenDrill] = useState<ManualItem | null>(null);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");

  const load = () => api.graduation()
    .then((r) => { setReport(r); setError(""); })
    .catch((e) => setError(e instanceof Error ? e.message : "failed to load"));

  useEffect(() => {
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, []);

  const submit = async (item: ManualItem, acknowledged: boolean) => {
    setBusy(true); setFormError("");
    try {
      const res = await fetch(`${BASE}/api/v1/graduation/drills/${item.name}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" },
        body: JSON.stringify({ acknowledged, notes: acknowledged ? notes : "" }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(typeof body.detail === "string" ? body.detail : `${res.status}`);
      }
      setOpenDrill(null); setNotes("");
      await load();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "could not save");
    } finally { setBusy(false); }
  };

  if (error && !report) {
    return <div className="error-banner">Couldn&apos;t load: {error}
      <br /><span style={{ fontSize: 12 }}>Run <code>cryptobot doctor</code> in backend/.</span>
    </div>;
  }
  if (!report) return <p className="empty">Loading…</p>;

  const manual = (report.manual_items ?? []) as unknown as ManualItem[];
  const manualDone = manual.filter((m) => m.done).length;

  return (
    <div>
      <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 10 }}>
        {report.automated_complete}/{report.automated_total} evidence targets ·
        {" "}{manualDone}/{manual.length} manual steps — what stands between paper
        trading and even considering real money
      </p>

      {report.items.map((item) => (
        <div key={item.name} style={{ marginBottom: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
            <span style={{ color: item.done ? "var(--green)" : "var(--text-muted)" }}>
              {item.done ? "✓ " : ""}{item.label}
            </span>
            <span style={{ fontFamily: "var(--mono)" }}>
              {item.current === null ? "—" : Number(item.current).toLocaleString(undefined, { maximumFractionDigits: 1 })}
              {" / "}{item.name === "net_pnl" ? "> 0" : item.target}{item.unit && ` ${item.unit}`}
            </span>
          </div>
          <div style={{ background: "var(--surface-2)", borderRadius: 999, height: 6, marginTop: 4 }}>
            <div style={{
              background: item.done ? "var(--green)" : "var(--accent)",
              width: `${Math.max(2, item.progress * 100)}%`, height: 6, borderRadius: 999,
            }} />
          </div>
        </div>
      ))}

      <div style={{ borderTop: "1px solid var(--border)", marginTop: 12, paddingTop: 8 }}>
        <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 6 }}>
          Manual steps — click one to see how to run it and record the result:
        </p>
        {manual.map((m) => (
          <button key={m.name} onClick={() => { setOpenDrill(m); setNotes(m.notes ?? ""); }}
            style={{
              display: "block", width: "100%", textAlign: "left", background: "none",
              border: "none", padding: "5px 0", fontSize: 12.5,
              color: m.done ? "var(--green)" : "var(--text)", cursor: "pointer",
            }}>
            {m.done ? "☑" : "☐"} {m.label}
            {m.done && m.acknowledged_at && (
              <span style={{ color: "var(--text-muted)", fontSize: 11 }}>
                {" "}— {new Date(m.acknowledged_at).toLocaleDateString()}
              </span>
            )}
          </button>
        ))}
      </div>

      <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 10, lineHeight: 1.5 }}>
        {report.note}
      </p>

      {openDrill && (
        <div className="modal-backdrop" onClick={() => setOpenDrill(null)}>
          <div className="card" style={{ maxWidth: 560, maxHeight: "85vh", overflowY: "auto" }}
            onClick={(e) => e.stopPropagation()}>
            <h2>{openDrill.label}</h2>

            {openDrill.why && (
              <p style={{ fontSize: 13, color: "var(--text-muted)", margin: "8px 0", lineHeight: 1.6 }}>
                {openDrill.why}
              </p>
            )}

            {openDrill.how && openDrill.how.length > 0 && (
              <>
                <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 10 }}>How to run it:</p>
                <ol style={{ fontSize: 12.5, paddingLeft: 20, lineHeight: 1.7 }}>
                  {openDrill.how.map((step, i) => (
                    <li key={i} style={{ fontFamily: step.includes(":") && step.match(/^[a-z.\\]/) ? "var(--mono)" : "inherit" }}>
                      {step}
                    </li>
                  ))}
                </ol>
              </>
            )}

            {openDrill.pass_criteria && (
              <p style={{ fontSize: 12.5, marginTop: 10, padding: "8px 10px",
                          background: "var(--surface-2)", borderRadius: 8, lineHeight: 1.6 }}>
                <strong style={{ fontWeight: 550 }}>Passes when:</strong> {openDrill.pass_criteria}
              </p>
            )}

            <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 12 }}>
              What did you observe? (required — this record is the evidence)
            </p>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)}
              rows={3} placeholder="e.g. Killed the trader with 1 open position; on restart it reconciled to the same position, no duplicates."
              style={{
                width: "100%", marginTop: 4, background: "var(--surface-2)",
                border: "1px solid var(--border-strong)", borderRadius: 8,
                padding: "8px 10px", color: "var(--text)", fontSize: 12.5,
                fontFamily: "inherit", resize: "vertical",
              }} />

            {formError && <p style={{ color: "var(--red)", fontSize: 12, marginTop: 6 }}>{formError}</p>}

            <p style={{ fontSize: 11, color: "var(--amber)", marginTop: 8, lineHeight: 1.5 }}>
              Only tick this if you actually ran the drill and it passed. An unearned
              tick removes the protection this gate exists to give you.
            </p>

            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 12 }}>
              <button onClick={() => setOpenDrill(null)} disabled={busy}>Cancel</button>
              {openDrill.done && (
                <button className="danger" disabled={busy}
                  onClick={() => submit(openDrill, false)}>Withdraw</button>
              )}
              <button className="primary" disabled={busy}
                onClick={() => submit(openDrill, true)}>
                {busy ? "saving…" : "It passed — record it"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
