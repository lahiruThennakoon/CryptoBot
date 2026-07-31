"use client";

import { useState } from "react";
import { api, Overview } from "@/lib/api";

/** High-risk actions use the server-side arm/confirm flow:
 *  1) POST /controls/arm → one-time token (60s TTL)
 *  2) operator confirms in the dialog
 *  3) token accompanies the destructive call. */
export function Controls({ overview, onAction }: { overview: Overview | null; onAction: () => void }) {
  const [confirming, setConfirming] = useState<"stop" | "resume" | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const run = async (fn: () => Promise<unknown>, label: string) => {
    setBusy(true);
    try {
      await fn();
      setMessage("");
    } catch (err) {
      setMessage(`${label} failed: ${err instanceof Error ? err.message : "error"}`);
    } finally {
      setBusy(false);
      setConfirming(null);
      onAction();
    }
  };

  const confirmed = async (kind: "stop" | "resume") => {
    await run(async () => {
      const { confirm_token } = await api.arm();
      if (kind === "stop") await api.emergencyStop(confirm_token);
      else await api.resume(confirm_token);
    }, kind === "stop" ? "Emergency stop" : "Resume");
  };

  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
      {message && <span style={{ color: "var(--red)", fontSize: 12 }}>{message}</span>}

      {overview?.paused || overview?.emergency_stop ? (
        <button disabled={busy} onClick={() => setConfirming("resume")}>Resume</button>
      ) : (
        <button disabled={busy} onClick={() => run(() => api.pause(), "Pause")}>Pause</button>
      )}
      <button className="danger" disabled={busy} onClick={() => setConfirming("stop")}>
        Emergency stop
      </button>

      {confirming && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", zIndex: 50,
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          <div className="card" style={{ maxWidth: 420 }}>
            <h2>{confirming === "stop" ? "Confirm emergency stop" : "Confirm resume"}</h2>
            <p style={{ fontSize: 13, color: "var(--text-muted)", margin: "8px 0 14px" }}>
              {confirming === "stop"
                ? "This closes all open paper positions immediately and blocks new orders until you explicitly resume. Continue?"
                : "Trading was halted. Resuming requires acknowledging the halt was reviewed. Continue?"}
            </p>
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button disabled={busy} onClick={() => setConfirming(null)}>Cancel</button>
              <button className="danger" disabled={busy} onClick={() => confirmed(confirming)}>
                {busy ? "Working…" : confirming === "stop" ? "Yes, stop everything" : "Yes, resume"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
