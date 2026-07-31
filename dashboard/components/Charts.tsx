"use client";

/** Dependency-free SVG charts: axes, gridlines, hover crosshair + tooltip.
 *  No external chart library — keeps the bundle small and avoids a build
 *  dependency, while giving real axis scales and interactivity. */

import { useRef, useState } from "react";

const PAD = { left: 54, right: 12, top: 12, bottom: 26 };

function niceTicks(min: number, max: number, count = 4): number[] {
  if (!isFinite(min) || !isFinite(max) || min === max) return [min];
  const span = max - min;
  const rough = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(rough)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= rough) ?? mag * 10;
  const start = Math.ceil(min / step) * step;
  const out: number[] = [];
  for (let v = start; v <= max + step * 0.001; v += step) out.push(Number(v.toFixed(10)));
  return out;
}

function fmtNum(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (abs >= 1000) return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (abs >= 1) return v.toFixed(2);
  return v.toPrecision(3);
}

interface HoverState { i: number; x: number; y: number }

function useHover(count: number, width: number) {
  const ref = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<HoverState | null>(null);
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const svg = ref.current;
    if (!svg || count === 0) return;
    const rect = svg.getBoundingClientRect();
    const vx = ((e.clientX - rect.left) / rect.width) * width;
    const inner = width - PAD.left - PAD.right;
    const ratio = Math.min(1, Math.max(0, (vx - PAD.left) / inner));
    setHover({ i: Math.round(ratio * (count - 1)), x: vx, y: 0 });
  };
  return { ref, hover, onMove, clear: () => setHover(null) };
}

function Axes({ width, height, yTicks, yScale, xLabels }: {
  width: number; height: number; yTicks: number[];
  yScale: (v: number) => number; xLabels: { at: number; text: string }[];
}) {
  return (
    <g>
      {yTicks.map((t) => (
        <g key={t}>
          <line x1={PAD.left} x2={width - PAD.right} y1={yScale(t)} y2={yScale(t)}
            stroke="var(--border)" strokeWidth={1} />
          <text x={PAD.left - 8} y={yScale(t) + 3.5} textAnchor="end"
            fill="var(--text-muted)" fontSize={10.5} fontFamily="var(--mono)">
            {fmtNum(t)}
          </text>
        </g>
      ))}
      {xLabels.map((l, i) => (
        <text key={i} x={l.at} y={height - 8} textAnchor="middle"
          fill="var(--text-muted)" fontSize={10.5}>{l.text}</text>
      ))}
    </g>
  );
}

function Tooltip({ x, width, lines, color }: {
  x: number; width: number; lines: string[]; color: string;
}) {
  const boxWidth = Math.max(...lines.map((l) => l.length)) * 5.6 + 16;
  const flip = x + boxWidth + 8 > width;
  return (
    <g transform={`translate(${flip ? x - boxWidth - 8 : x + 8}, ${PAD.top + 4})`}>
      <rect width={boxWidth} height={lines.length * 14 + 10} rx={6}
        fill="var(--surface-3)" stroke={color} strokeWidth={1} opacity={0.97} />
      {lines.map((l, i) => (
        <text key={i} x={8} y={17 + i * 14} fill="var(--text)" fontSize={11}
          fontFamily="var(--mono)">{l}</text>
      ))}
    </g>
  );
}

/* ── Area / line chart ─────────────────────────────────────────────── */
export function AreaChart({ points, height = 220, valueLabel = "value", baseline }: {
  points: { t: string; v: number }[]; height?: number;
  valueLabel?: string; baseline?: number;
}) {
  const W = 760;
  const { ref, hover, onMove, clear } = useHover(points.length, W);
  if (points.length < 2) {
    return <p className="empty">Not enough data yet — the chart appears once snapshots accumulate.</p>;
  }
  const values = points.map((p) => p.v);
  const base = baseline ?? values[0];
  const min = Math.min(...values, base);
  const max = Math.max(...values, base);
  const pad = (max - min) * 0.08 || Math.abs(max) * 0.01 || 1;
  const lo = min - pad, hi = max + pad;
  const xAt = (i: number) => PAD.left + (i * (W - PAD.left - PAD.right)) / (points.length - 1);
  const yAt = (v: number) => height - PAD.bottom - ((v - lo) / (hi - lo)) * (height - PAD.top - PAD.bottom);

  const line = points.map((p, i) => `${xAt(i).toFixed(1)},${yAt(p.v).toFixed(1)}`).join(" ");
  const area = `${PAD.left},${yAt(lo)} ${line} ${xAt(points.length - 1)},${yAt(lo)}`;
  const up = values[values.length - 1] >= base;
  const color = up ? "var(--green)" : "var(--red)";
  const step = Math.max(1, Math.floor(points.length / 5));
  const xLabels = points.filter((_, i) => i % step === 0).map((p, k) => ({
    at: xAt(k * step),
    text: new Date(p.t).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
  }));

  return (
    <svg ref={ref} viewBox={`0 0 ${W} ${height}`} onMouseMove={onMove} onMouseLeave={clear}
      style={{ width: "100%", height: "auto", display: "block", cursor: "crosshair" }}
      role="img" aria-label={`${valueLabel} over time`}>
      <Axes width={W} height={height} yTicks={niceTicks(lo, hi)} yScale={yAt} xLabels={xLabels} />
      <line x1={PAD.left} x2={W - PAD.right} y1={yAt(base)} y2={yAt(base)}
        stroke="var(--border-strong)" strokeDasharray="4 4" />
      <polygon points={area} fill={color} opacity={0.10} />
      <polyline points={line} fill="none" stroke={color} strokeWidth={2}
        strokeLinejoin="round" />
      {hover && points[hover.i] && (
        <>
          <line x1={xAt(hover.i)} x2={xAt(hover.i)} y1={PAD.top} y2={height - PAD.bottom}
            stroke="var(--border-strong)" />
          <circle cx={xAt(hover.i)} cy={yAt(points[hover.i].v)} r={3.5} fill={color} />
          <Tooltip x={xAt(hover.i)} width={W} color={color} lines={[
            new Date(points[hover.i].t).toLocaleString(undefined,
              { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }),
            `${valueLabel}: ${points[hover.i].v.toLocaleString(undefined, { maximumFractionDigits: 2 })}`,
            `vs start: ${(points[hover.i].v - base >= 0 ? "+" : "")}${(points[hover.i].v - base).toFixed(2)}`,
          ]} />
        </>
      )}
    </svg>
  );
}

/* ── Candlestick chart ─────────────────────────────────────────────── */
export interface Candle { t: string; o: number; h: number; l: number; c: number; v: number }

export function CandleChart({ candles, height = 300, symbol = "" }: {
  candles: Candle[]; height?: number; symbol?: string;
}) {
  const W = 760;
  const { ref, hover, onMove, clear } = useHover(candles.length, W);
  if (candles.length < 2) {
    return <p className="empty">
      No candles stored for this pair yet. Run <code>cryptobot import-history</code> or
      let the collector run to populate the chart.
    </p>;
  }
  const volH = 42;
  const priceH = height - volH;
  const lo = Math.min(...candles.map((c) => c.l));
  const hi = Math.max(...candles.map((c) => c.h));
  const pad = (hi - lo) * 0.06 || 1;
  const yLo = lo - pad, yHi = hi + pad;
  const inner = W - PAD.left - PAD.right;
  const slot = inner / candles.length;
  const bodyW = Math.max(1.2, Math.min(9, slot * 0.62));
  const xAt = (i: number) => PAD.left + slot * (i + 0.5);
  const yAt = (v: number) => priceH - PAD.bottom - ((v - yLo) / (yHi - yLo)) * (priceH - PAD.top - PAD.bottom);
  const maxVol = Math.max(...candles.map((c) => c.v)) || 1;
  const step = Math.max(1, Math.floor(candles.length / 5));
  const xLabels = candles.filter((_, i) => i % step === 0).map((c, k) => ({
    at: xAt(k * step),
    text: new Date(c.t).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
  }));

  return (
    <svg ref={ref} viewBox={`0 0 ${W} ${height}`} onMouseMove={onMove} onMouseLeave={clear}
      style={{ width: "100%", height: "auto", display: "block", cursor: "crosshair" }}
      role="img" aria-label={`${symbol} price candles`}>
      <Axes width={W} height={priceH} yTicks={niceTicks(yLo, yHi)} yScale={yAt} xLabels={xLabels} />
      {candles.map((c, i) => {
        const up = c.c >= c.o;
        const color = up ? "var(--green)" : "var(--red)";
        const bodyTop = yAt(Math.max(c.o, c.c));
        const bodyBottom = yAt(Math.min(c.o, c.c));
        return (
          <g key={i}>
            <line x1={xAt(i)} x2={xAt(i)} y1={yAt(c.h)} y2={yAt(c.l)}
              stroke={color} strokeWidth={1} opacity={0.85} />
            <rect x={xAt(i) - bodyW / 2} y={bodyTop} width={bodyW}
              height={Math.max(1, bodyBottom - bodyTop)} fill={color} opacity={0.9} />
            <rect x={xAt(i) - bodyW / 2} y={priceH + (volH - 12) * (1 - c.v / maxVol)}
              width={bodyW} height={(volH - 12) * (c.v / maxVol)} fill={color} opacity={0.28} />
          </g>
        );
      })}
      <text x={PAD.left} y={height - 2} fill="var(--text-muted)" fontSize={9.5}>volume</text>
      {hover && candles[hover.i] && (
        <>
          <line x1={xAt(hover.i)} x2={xAt(hover.i)} y1={PAD.top} y2={priceH - PAD.bottom}
            stroke="var(--border-strong)" />
          <Tooltip x={xAt(hover.i)} width={W}
            color={candles[hover.i].c >= candles[hover.i].o ? "var(--green)" : "var(--red)"}
            lines={[
              new Date(candles[hover.i].t).toLocaleString(undefined,
                { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }),
              `O ${fmtNum(candles[hover.i].o)}  H ${fmtNum(candles[hover.i].h)}`,
              `L ${fmtNum(candles[hover.i].l)}  C ${fmtNum(candles[hover.i].c)}`,
              `vol ${fmtNum(candles[hover.i].v)}`,
            ]} />
        </>
      )}
    </svg>
  );
}

/* ── Bar chart (daily PnL) ─────────────────────────────────────────── */
export function BarChart({ bars, height = 200, unit = "USDT" }: {
  bars: { label: string; value: number; extra?: string }[]; height?: number; unit?: string;
}) {
  const W = 760;
  const { ref, hover, onMove, clear } = useHover(bars.length, W);
  if (!bars.length) return <p className="empty">No closed trades yet — nothing to chart.</p>;
  const values = bars.map((b) => b.value);
  const max = Math.max(...values, 0);
  const min = Math.min(...values, 0);
  const pad = (max - min) * 0.1 || 1;
  const yLo = min - pad, yHi = max + pad;
  const inner = W - PAD.left - PAD.right;
  const slot = inner / bars.length;
  const barW = Math.max(2, Math.min(28, slot * 0.6));
  const xAt = (i: number) => PAD.left + slot * (i + 0.5);
  const yAt = (v: number) => height - PAD.bottom - ((v - yLo) / (yHi - yLo)) * (height - PAD.top - PAD.bottom);
  const zero = yAt(0);
  const step = Math.max(1, Math.floor(bars.length / 6));

  return (
    <svg ref={ref} viewBox={`0 0 ${W} ${height}`} onMouseMove={onMove} onMouseLeave={clear}
      style={{ width: "100%", height: "auto", display: "block", cursor: "crosshair" }}
      role="img" aria-label="daily result">
      <Axes width={W} height={height} yTicks={niceTicks(yLo, yHi)} yScale={yAt}
        xLabels={bars.filter((_, i) => i % step === 0).map((b, k) => ({
          at: xAt(k * step), text: b.label.slice(5),
        }))} />
      <line x1={PAD.left} x2={W - PAD.right} y1={zero} y2={zero} stroke="var(--border-strong)" />
      {bars.map((b, i) => {
        const color = b.value >= 0 ? "var(--green)" : "var(--red)";
        const y = b.value >= 0 ? yAt(b.value) : zero;
        return (
          <rect key={i} x={xAt(i) - barW / 2} y={y} width={barW}
            height={Math.max(1, Math.abs(yAt(b.value) - zero))} fill={color}
            opacity={hover && hover.i === i ? 1 : 0.8} rx={1.5} />
        );
      })}
      {hover && bars[hover.i] && (
        <Tooltip x={xAt(hover.i)} width={W}
          color={bars[hover.i].value >= 0 ? "var(--green)" : "var(--red)"}
          lines={[
            bars[hover.i].label,
            `${bars[hover.i].value >= 0 ? "+" : ""}${bars[hover.i].value.toFixed(2)} ${unit}`,
            ...(bars[hover.i].extra ? [bars[hover.i].extra as string] : []),
          ]} />
      )}
    </svg>
  );
}
