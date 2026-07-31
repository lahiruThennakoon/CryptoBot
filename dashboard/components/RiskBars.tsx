"use client";

import { EquityPoint, Overview } from "@/lib/api";

function Bar({ label, used, limit, unit }: { label: string; used: number; limit: number; unit: string }) {
  const pct = limit > 0 ? Math.min(100, (used / limit) * 100) : 0;
  const color = pct >= 90 ? "var(--red)" : pct >= 60 ? "var(--amber)" : "var(--green)";
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
        <span style={{ color: "var(--text-muted)" }}>{label}</span>
        <span style={{ fontFamily: "var(--mono)" }}>{used.toFixed(2)} / {limit}{unit}</span>
      </div>
      <div style={{ background: "var(--surface-2)", borderRadius: 999, height: 6, marginTop: 4 }}>
        <div style={{ background: color, width: `${pct}%`, height: 6, borderRadius: 999 }} />
      </div>
    </div>
  );
}

export function RiskBars({ overview, equityWindow }: { overview: Overview | null; equityWindow: EquityPoint[] }) {
  if (!overview) return <p style={{ color: "var(--text-muted)" }}>Loading…</p>;
  const limits = overview.risk_limits;
  const equity = overview.equity ?? 0;

  const peak = equityWindow.reduce((m, p) => Math.max(m, p.equity), equity || 1);
  const drawdownPct = peak > 0 ? Math.max(0, ((peak - (equity || peak)) / peak) * 100) : 0;
  const exposurePct = equity > 0 ? ((overview.exposure ?? 0) / equity) * 100 : 0;

  return (
    <div>
      <Bar label="Drawdown" used={drawdownPct} limit={(limits.max_drawdown_pct ?? 0.15) * 100} unit="%" />
      <Bar label="Exposure" used={exposurePct} limit={(limits.max_exposure_pct ?? 0.25) * 100} unit="%" />
      <Bar label="Open positions" used={overview.open_positions} limit={limits.max_positions ?? 3} unit="" />
      {overview.last_risk_event && (
        <p style={{ fontSize: 12, color: "var(--amber)", marginTop: 8 }}>
          Last risk event: {overview.last_risk_event.type} — {overview.last_risk_event.detail}
        </p>
      )}
    </div>
  );
}
