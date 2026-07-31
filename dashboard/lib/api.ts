const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const TOKEN = process.env.NEXT_PUBLIC_API_TOKEN ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}/api/v1${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${TOKEN}`,
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export interface Overview {
  mode: string;
  live_trading: string;
  paused: boolean;
  emergency_stop: boolean;
  equity: number | null;
  cash: number | null;
  exposure: number | null;
  open_positions: number;
  risk_limits: Record<string, number>;
  last_risk_event: { type: string; detail: string; at: string } | null;
  disclaimer: string;
}

export interface EquityPoint { t: string; equity: number; exposure: number }
export interface Position {
  symbol: string; qty: string; entry: string; stop: string | null;
  take_profit: string | null; strategy: string; opened_at: string;
  realized_pnl: string; exit_reason: string; closed_at: string | null;
}
export interface Fill {
  symbol: string; side: string; role: string; price: string; qty: string;
  fee: string; at: string;
}
export interface SignalEntry {
  symbol: string; strategy: string; side: string; confidence: number;
  regime: string; outcome: string; rejection_code: string | null;
  detail: string; at: string;
}

export interface NoTradeReason {
  code: string; count: number; title: string; explanation: string; protective: boolean;
}
export interface NoTradeReport {
  hours: number; trades_executed: number; signals_skipped: number;
  summary: string; reasons: NoTradeReason[];
}
export interface GraduationItem {
  name: string; label: string; current: number | null; target: number;
  unit: string; done: boolean; progress: number;
}
export interface GraduationReport {
  items: GraduationItem[];
  manual_items: { name: string; label: string; done: boolean; manual: boolean }[];
  automated_complete: number; automated_total: number; note: string;
}
export interface StrategyInfo {
  name: string; timeframe: string; required_conditions: string;
  invalid_when: string; allowed_regimes: string[];
}
export interface LabResult {
  strategy: string; symbol: string; interval: string; bars: number;
  period: { from: string; to: string };
  verdict: { grade: string; headline: string; detail: string };
  metrics: {
    net_return_pct: number; buy_hold_return_pct: number; max_drawdown_pct: number;
    n_trades: number; win_rate: number | null; expectancy: number | null;
    total_fees: number; sharpe: number | null; exposure_time_pct: number;
  };
  rejections: Record<string, number>;
  regime_distribution: Record<string, number>;
  note: string;
}

export interface PairInfo {
  symbol: string; base_asset: string; quote_asset: string; status: string;
  enabled: boolean; selectable: boolean; not_selectable_reason: string;
  warnings: string[]; last_price: number; price_change_pct_24h: number;
  quote_volume_24h: number; spread_pct: number; volatility_24h_pct: number;
}
export interface Decision {
  symbol: string; decision: string; status: string; confidence: number;
  score: number; supporting: Record<string, number>;
  conflicting: Record<string, number>; entry_estimate: number | null;
  stop_price: number | null; take_profit: number | null;
  expected_holding_bars: number | null; est_fees: number; est_spread: number;
  est_slippage: number; expected_gross_return: number | null;
  expected_net_return: number | null; reasons: { list: string[] } | string[];
  at: string; advice_disclaimer: string;
}

export interface CandlesResponse {
  symbol: string; interval: string; count: number;
  candles: { t: string; o: number; h: number; l: number; c: number; v: number }[];
  source: string;
}
export interface DailyPerformance {
  days: { date: string; net_pnl: number; fees: number; gross_pnl: number; trades: number }[];
  value_kind: string; note: string;
}

export const api = {
  overview: () => request<Overview>("/overview"),
  equity: (hours = 168) => request<EquityPoint[]>(`/equity?hours=${hours}`),
  positions: (status = "open") => request<Position[]>(`/positions?status=${status}`),
  fills: (limit = 30) => request<Fill[]>(`/fills?limit=${limit}`),
  signals: (limit = 50) => request<SignalEntry[]>(`/signals?limit=${limit}`),
  pause: () => request<{ status: string }>("/controls/pause", { method: "POST" }),
  arm: () => request<{ confirm_token: string }>("/controls/arm", { method: "POST" }),
  resume: (token: string) =>
    request<{ status: string }>("/controls/resume", {
      method: "POST",
      body: JSON.stringify({ confirm_token: token }),
    }),
  emergencyStop: (token: string) =>
    request<{ status: string }>("/controls/emergency-stop", {
      method: "POST",
      body: JSON.stringify({ confirm_token: token }),
    }),
  noTrade: (hours = 24) => request<NoTradeReport>(`/explain/no-trade?hours=${hours}`),
  graduation: () => request<GraduationReport>("/graduation"),
  labStrategies: () => request<StrategyInfo[]>("/lab/strategies"),
  labBacktest: (strategy: string, symbol = "BTCUSDT", interval = "1h") =>
    request<LabResult>("/lab/backtest", {
      method: "POST",
      body: JSON.stringify({ strategy, symbol, interval }),
    }),
  pairs: (search = "") => request<PairInfo[]>(`/pairs?search=${encodeURIComponent(search)}`),
  enablePair: (symbol: string) =>
    request<{ enabled: boolean; warnings: string[] }>(`/pairs/${symbol}/enable`, { method: "POST" }),
  disablePair: (symbol: string) =>
    request<{ enabled: boolean }>(`/pairs/${symbol}/disable`, { method: "POST" }),
  currentDecisions: () => request<Decision[]>("/decisions/current"),
  candles: (symbol: string, interval = "1h", limit = 200) =>
    request<CandlesResponse>(`/candles?symbol=${symbol}&interval=${interval}&limit=${limit}`),
  dailyPerformance: (days = 30) =>
    request<DailyPerformance>(`/performance/daily?days=${days}`),
};
