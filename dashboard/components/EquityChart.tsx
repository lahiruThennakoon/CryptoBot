"use client";

import { EquityPoint } from "@/lib/api";
import { AreaChart } from "@/components/Charts";

export function EquityChart({ points }: { points: EquityPoint[] }) {
  return (
    <AreaChart
      points={points.map((p) => ({ t: p.t, v: p.equity }))}
      valueLabel="equity"
      height={230}
    />
  );
}
