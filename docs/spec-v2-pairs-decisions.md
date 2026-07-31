# Specification v2 — User-Selected Pairs, Live Decisions, Sessions

> Extends `prd.md` and `architecture.md`. Draft v2.0 · 2026-08-01
> **Framing:** the bot pursues profitable opportunities while controlling risk. It cannot guarantee a profit on any given day, will never manufacture trades to hit a target, never raises risk to recover losses, never uses martingale, never hides unrealized losses, and never reports gross as net. "No trade" is a successful risk-management decision. Live-money trading remains disabled.

## 1. Updated requirements (delta to prd.md)

### FR-14 Trading-pair selection
- FR-14.1 Retrieve available Spot pairs from Binance `exchangeInfo`; tradability judged against the ACTIVE venue (testnet in testnet/paper modes).
- FR-14.2 Searchable catalog with base/quote asset, live price, 24h change, volume, spread, liquidity — market stats from Binance live public REST (real prices; no key).
- FR-14.3 Enable/disable individual pairs; multiple selection; selections persisted (`pair_settings`).
- FR-14.4 Warnings before enabling: low liquidity (24h quote volume below threshold), wide spread, high 24h volatility.
- FR-14.5 Pairs that are not `TRADING`, unsupported quote assets, or restricted → not selectable (server-enforced, not just UI).
- FR-14.6 Per-pair overrides: risk-per-trade, max position %, min confidence, allowed strategies.
- FR-14.7 Defaults: BTCUSDT + ETHUSDT enabled (testnet examples). **The bot never trades a pair the user has not explicitly enabled** — enforced in the runtime, not the UI.

### FR-15 Per-pair decision engine
- FR-15.1 On every closed strategy-timeframe candle, produce a decision per enabled pair: BUY / SELL / HOLD / CLOSE / NO_TRADE, plus operational statuses RISK_BLOCKED and DATA_UNAVAILABLE.
- FR-15.2 Decisions come from a configurable **signal-scoring system** (§6), never a single indicator.
- FR-15.3 Every decision record contains: pair, decision, confidence, supporting signals, conflicting signals, estimated entry, stop-loss, take-profit, expected holding period, estimated fees/spread/slippage, expected gross and net return, and accept/reject reasons. Persisted append-only.
- FR-15.4 Stale/missing data → DATA_UNAVAILABLE and no trading decisions until the feed recovers.
- FR-15.5 UI statuses (Strong Buy…Data Unavailable) are decision support, never financial advice — labeled as such.

### FR-16 Opportunity ranking
- FR-16.1 Each cycle, qualifying BUY decisions across pairs are ranked by expected net return per unit of risk (net edge ÷ stop distance).
- FR-16.2 Highly correlated candidates (rolling return correlation > threshold, default 0.8) → only the strongest is taken.
- FR-16.3 Only the top-N strongest opportunities may execute, subject to all limits; zero qualifying opportunities is a normal outcome.

### FR-17 Sessions & daily objective
- FR-17.1 Configurable session start/end (UTC), enabled weekdays, overnight policy (hold / close at session end).
- FR-17.2 Configurable daily profit target with protection modes: `stop_trading` (default), `reduce_size`, `raise_confidence`, `exceptional_only`.
- FR-17.3 Config validation rejects unsafe/contradictory combinations (e.g. stop-loss ≥ take-profit, target below cost floor, zero trading days, session end ≤ start).
- FR-17.4 End of session: stop new entries → apply overnight policy → cancel stray orders → reconcile with the exchange → EOD report separating realized / unrealized / gross / fees / slippage / net / ending equity.

### FR-18 Operational modes
- `analysis` — full analysis and decision records, **no orders of any kind**.
- `paper` — simulated fills against live data with full cost model (default).
- `testnet` — real orders to Binance Spot Testnet after all checks.
- Live-money mode: **absent**. The mode is displayed prominently everywhere.

### FR-19 Notifications (delta)
Added events: strong opportunity detected, order lifecycle (created/filled/partial/rejected/canceled), stop/TP triggered, daily profit target reached, session ended + EOD report ready. All messages avoid any claim of guaranteed future profit.

## 2. Updated architecture (delta)

```mermaid
flowchart LR
    subgraph New["v2 additions"]
        CAT[Pair Catalog<br/>exchangeInfo + 24h stats + warnings]
        PS[(pair_settings)]
        DEC[Decision Engine<br/>signal scoring]
        RANK[Opportunity Ranker<br/>corr-aware top-N]
        SESS[Session Policy<br/>times · days · profit target]
        ROUTE[Execution Router<br/>analysis | paper | testnet]
    end
    MD[Market data WS] --> DEC
    STRAT[Strategies] --> DEC
    ML[Deployed model?] -.-> DEC
    CAT --> PS --> DEC
    DEC --> RANK --> SESS --> RISK[Risk Engine — veto] --> ROUTE
    ROUTE -->|paper| PB[Paper broker]
    ROUTE -->|testnet| TB[Testnet broker → BinanceSpotAdapter]
    ROUTE -->|analysis| X[No orders]
    DEC --> DB[(decisions)]
```

Order of authority (unchanged in spirit): user pair enablement → data health → strategy/scoring → cost gate → session policy → **risk engine (final veto)** → execution router.

## 3. Updated database schema (delta)

```sql
pair_settings (
  symbol text PK REFERENCES instruments(symbol),
  enabled bool DEFAULT false,             -- bot NEVER trades when false
  risk_per_trade numeric NULL,            -- per-pair overrides (NULL = global)
  max_position_pct numeric NULL,
  min_confidence numeric NULL,
  allowed_strategies jsonb NULL,          -- NULL = all enabled strategies
  updated_at timestamptz, updated_by text
);

session_configs (                          -- one active row per account
  id uuid PK, account_id uuid FK,
  session_start_utc time DEFAULT '00:00', session_end_utc time DEFAULT '23:59',
  trading_days jsonb DEFAULT '[0,1,2,3,4,5,6]',
  overnight_policy text DEFAULT 'hold',    -- 'hold' | 'close_at_session_end'
  daily_profit_target_pct numeric NULL,    -- NULL = no target
  target_protection text DEFAULT 'stop_trading',
  max_capital numeric NULL, updated_at timestamptz, version int
);

decisions (                                -- append-only
  id bigserial PK, account_id uuid FK, symbol text, decision text,
  status text,        -- strong_buy|buy|hold|sell|strong_sell|no_trade|risk_blocked|data_unavailable
  confidence numeric, score numeric,
  supporting jsonb, conflicting jsonb,     -- named signals with component scores
  entry_estimate numeric NULL, stop_price numeric NULL, take_profit numeric NULL,
  expected_holding_bars int NULL,
  est_fees numeric, est_spread numeric, est_slippage numeric,
  expected_gross_return numeric NULL, expected_net_return numeric NULL,
  reasons jsonb,                           -- accept/reject reasons incl. codes
  created_at timestamptz
);
```

## 4. Updated API endpoints (delta, all under /api/v1, bearer-auth)

| Method | Path | Purpose |
|---|---|---|
| GET | `/pairs?search=` | catalog: tradable pairs + live stats + warnings + enabled flag |
| POST | `/pairs/{symbol}/enable` · `/disable` | toggle (server validates selectability) |
| PATCH | `/pairs/{symbol}/settings` | per-pair risk/strategy overrides (validated) |
| GET | `/decisions?symbol=&limit=` | latest decision records incl. reasons |
| GET | `/decisions/current` | latest decision per enabled pair (drives the UI table) |
| GET/PUT | `/session` | session config; PUT validates and rejects unsafe combos |
| GET | `/overview` | now also returns execution mode + session state + profit-target state |

## 5. WebSocket data-flow design

```
Binance WS (per enabled pair)
  ├── kline_1m .. kline_4h ──► candle store ──► staleness monitor
  │                                └─► position protection (stops/TP) every 1m close
  ├── bookTicker ──► live bid/ask → spread, entry estimates      (Redis, TTL 10s)
  └── depth20@1s ──► order-book imbalance, liquidity depth       (Redis, TTL 10s)

Strategy-timeframe close (e.g. 1h) per enabled pair:
  indicators (MA/EMA/RSI/MACD/BB/ATR/momentum/vol/trend/S-R/breakout)
  + book features (imbalance, spread, depth)  + BTC correlation + multi-TF direction
  ──► Decision Engine ──► decision record ──► ranking ──► session ──► risk ──► router

REST is used ONLY for: historical backfill, exchangeInfo/24h stats, account
snapshots, and post-disconnect reconciliation.
Stale feed (no event within threshold) ──► DATA_UNAVAILABLE, decisions suspended.
Pair enable/disable takes effect on the next event loop tick; disabled pairs are
filtered at the runtime boundary (defense in depth vs UI bugs).
```

## 6. Signal-scoring design

Score ∈ [−1, +1] = Σ wᵢ·componentᵢ (weights configurable, defaults shown):

| Component (wt) | Source | Range |
|---|---|---|
| Strategy ensemble (0.35) | mean of entry/exit signals × confidence from enabled strategies | −1..+1 |
| Trend confirmation (0.15) | MA slope + MACD histogram sign + multi-TF agreement | −1..+1 |
| Momentum (0.10) | RSI distance from 50, N-bar return | −1..+1 |
| Volume confirmation (0.10) | volume vs its SMA | 0..+1 |
| Regime fit (0.10) | decision regime ∈ strategy's allowed set | −1 or +1 |
| ML confidence (0.10) | deployed model P(up) − 0.5, ×2; 0 when no model | −1..+1 |
| Order-book imbalance (0.05) | (bidVol−askVol)/(bid+ask) top levels | −1..+1 |
| Volatility penalty (−) (0.05) | ATR percentile above threshold subtracts | −1..0 |

Hard gates (not part of the score — they override it): data health, pair enabled,
spread ≤ max, liquidity ≥ min, cost gate (expected net > costs + margin),
session policy, risk engine. A perfect score with a failed gate = NO_TRADE.

Status mapping: score ≥ +0.6 → Strong Buy · ≥ +0.35 → Buy · ≤ −0.6 → Strong Sell ·
≤ −0.35 → Sell · gate-blocked → Risk Blocked / No Trade / Data Unavailable · else Hold.
(Sell/Strong Sell act on open positions only — spot, long-only.)

## 7. Risk-validation flow

```
decision(BUY) ─► pair enabled? ─► data fresh? ─► spread/liquidity ok? ─► cost gate?
  ─► session open? ─► profit-target protection state? ─► ranking selected?
  ─► RISK ENGINE (final veto): confidence ≥ min · stop valid · size from risk% ·
     max position/exposure/positions · trades/hour/day · daily loss · drawdown ·
     consecutive losses · cooldowns
  ─► execution router (analysis: record only · paper: sim fill · testnet: real order)
Every rejection at any stage → decision record reason + signal log + plain-language
explanation. Exits (stop/TP/trailing/invalid-signal/reversal/volatility/liquidity/
max-hold/emergency) bypass entry gates — closing risk is always allowed.
```

## 8. UI wireframe — "Trading pairs" section

```
┌ Trading pairs ──────────────────────────── mode: PAPER · session: OPEN ┐
│ [search…]                          [show: enabled | all]               │
│ ─────────────────────────────────────────────────────────────────────  │
│ ● BTCUSDT  67,412.50  +2.1%  ↑trend   [STRONG BUY 0.71]  spread 0.01%  │
│   vol 24h $2.1B · volat. med · position: 0.008 @ 66,900 (+0.6%)        │
│   strategy: ma_trend · risk: ok · analysed 12:00:03      [▼ why]       │
│   └ why: 3 supporting (ensemble +0.42, trend +0.13, volume +0.08)      │
│          1 conflicting (volatility −0.04) · est. net +0.9% after costs │
│          stop 65,900 · take-profit 69,100 · est. fees 0.20%            │
│ ○ ETHUSDT  3,412.10  −0.4%  →range    [HOLD 0.12]        spread 0.02%  │
│ ○ SOLUSDT  188.20    +5.9%  ↑trend    [DATA UNAVAILABLE] ⚠ enable?     │
│   ⚠ before enabling: 24h volume $95M (low) · volatility high           │
│ ─────────────────────────────────────────────────────────────────────  │
│ Statuses are decision support, not financial advice. No profit is      │
│ guaranteed; the bot will skip trading whenever checks fail.            │
└─────────────────────────────────────────────────────────────────────────┘
```

## 9. Test scenarios

1. Disabled pair generates a strategy signal → decision recorded, **no order**, reason PAIR_DISABLED.
2. Stale feed → status DATA_UNAVAILABLE; no decisions executed until recovery.
3. Score high but spread above max → NO_TRADE with WIDE_SPREAD reason (gate beats score).
4. Two correlated pairs both qualify → only the higher-ranked executes.
5. Daily profit target hit with `stop_trading` → no new entries; exits still work; state visible.
6. `raise_confidence` mode → sub-threshold signal rejected, exceptional signal accepted.
7. Session closed (time/day) → entries blocked with OUT_OF_SESSION; overnight `close_at_session_end` closes positions at session end.
8. Contradictory config (SL ≥ TP, end ≤ start, empty days, target ≤ cost floor) → PUT /session rejected with explanation.
9. Analysis mode → decisions recorded, zero orders of any kind.
10. Testnet mode → order routed through the real adapter with filter validation and idempotent client ID (real Testnet E2E, opt-in suite).
11. Decision record completeness: every persisted decision has all FR-15.3 fields.
12. Ranking determinism: same inputs → same ranking (seeded, no wall-clock dependence).
13. EOD with open position → report separates realized vs unrealized; never nets them silently.
14. Live-money impossibility: no code path constructs a live execution router (asserted by test).

## 10. Step-by-step implementation plan

1. DB: `pair_settings`, `session_configs`, `decisions` (+ migration).
2. Pair catalog service: exchangeInfo (active venue) + live 24h stats + warnings + selectability.
3. Scoring engine (pure) + decision records + status mapping.
4. Opportunity ranker (pure, correlation-aware).
5. Session policy (pure validation + gates + profit-target protection).
6. Execution router + testnet broker; analysis mode.
7. Runtime integration (enabled pairs boundary, decision persistence, notifications).
8. API endpoints.
9. UI Trading Pairs section + explanation panel.
10. Tests at each step; sandbox verification of all pure modules; Testnet E2E additions to the opt-in suite.
```
Steps 3–5 are pure and fully testable offline; 2, 6, 7 carry the I/O.
```
