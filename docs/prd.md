# Product Requirements Document — CryptoBot

> BMAD Phase: **PM → PRD** · Draft v1.0 · 2026-08-01
> Upstream: `brief.md` · Downstream: `architecture.md`, epics/stories (Phase 2+)

---

## 1. Functional requirements

### FR-1 Market data
- FR-1.1 Subscribe to Binance WebSocket kline, trade, and depth streams for configured pairs.
- FR-1.2 Detect stale data (no update within configurable threshold) and flag the pair unhealthy; risk engine blocks new entries on unhealthy pairs.
- FR-1.3 Reconnect after WebSocket interruption with exponential backoff + jitter; resubscribe and backfill gaps via REST klines.
- FR-1.4 Persist candles to PostgreSQL; cache latest ticks in Redis.
- FR-1.5 Historical importer downloads and validates kline history (gap detection, duplicate rejection, chronological ordering).

### FR-2 Exchange integration (Binance Spot)
- FR-2.1 `ExchangeAdapter` interface; `BinanceSpotAdapter` is the only v1 implementation. Testnet and live use separate base URLs and separate credentials.
- FR-2.2 Synchronize server time before signed requests; refuse signed calls when drift exceeds threshold.
- FR-2.3 Load trading rules from `exchangeInfo` at startup and on schedule; validate tick size, step size, min quantity, and min notional locally before any order.
- FR-2.4 Respect request-weight, order-count, and connection limits via a client-side rate limiter; honor 429/418 responses and `Retry-After`.
- FR-2.5 Unique client order IDs for idempotency; a submission is never retried without first querying the order's state on the exchange.
- FR-2.6 Handle partial fills, rejections, cancellations, expirations; track weighted average fill price and per-fill fees.
- FR-2.7 User-data stream for order/balance updates; listen-key keepalive; fall back to REST polling on stream failure.
- FR-2.8 On startup and after any disconnect: reconcile local orders, positions, and balances against the exchange before trading resumes.
- FR-2.9 Never log API secrets, signatures, or full signed URLs.
- FR-2.10 No endpoint or parameter may be used without verification against current official Binance Spot API documentation (Phase 2 implementation rule).

### FR-3 Strategies
- FR-3.1 `Strategy` interface; each strategy declares: required market conditions, entry rules, exit rules, stop-loss logic, take-profit logic, max holding period, invalid-signal conditions, cooldown, supported pairs/timeframes, and excluded market regimes.
- FR-3.2 Baseline strategies: MA trend-following; momentum + volume confirmation; RSI mean reversion; breakout + volatility filter; multi-timeframe trend confirmation.
- FR-3.3 Signal-scoring/ensemble mechanism requires configurable confirmation before a trade is permitted; strategies are never blindly combined.
- FR-3.4 "No trade" is a first-class outcome and is logged with reasons.

### FR-4 Signal validation & risk (veto authority)
- FR-4.1 Every signal passes: signal-validation (data quality, regime fit, confidence threshold) → cost gate (expected return after conservative costs > safety margin) → risk engine (all limits in `risk-policy.md`).
- FR-4.2 Risk engine may reject any signal; every rejection is persisted with a machine-readable reason code.
- FR-4.3 Breach of daily-loss, drawdown, or infrastructure limits → trading halts (no new entries; exits still managed) and requires explicit operator review via `POST /controls/clear-halt` to resume.
- FR-4.4 **Near-miss transparency (learning).** When the top ranked candidate is rejected only because expected edge or confidence falls within a configurable margin of passing (default: within 0.05 absolute of the threshold), persist it as a near-miss with: symbol, scores, required vs actual edge, rejection code, and a plain-language gap summary. Surface via dashboard, EOD report (top N per day), and read-only API/assistant tools. **Does not relax any gate** — visibility for operator learning only.

### FR-5 Position sizing & portfolio
- FR-5.1 Sizing from configured risk-per-trade %, stop distance, and exchange filters; rounded down to step size; verified against min notional.
- FR-5.2 Portfolio tracker maintains balances, positions, exposure, realized/unrealized PnL, recomputed after every fill.
- FR-5.3 Never sell more than available balance; never exceed max exposure or max simultaneous positions.
- FR-5.4 **Fixed entry notional (optional).** Operator may set a quote-currency cap per new entry (e.g. $10, $25). When enabled:
  - **Target mode:** each approved entry uses `min(fixed_notional, risk-based size, max_position_pct cap, exposure headroom)` — never exceeds the fixed amount; may be lower when portfolio limits bind.
  - **Validation:** reject entries when `fixed_notional` is below the pair's exchange min notional; surface a clear reason code (`FIXED_NOTIONAL_BELOW_MIN`).
  - **Profit discipline unchanged:** fixed sizing does not bypass FR-4.1 cost gate, confidence thresholds, or ranked-batch selection — the bot still skips trades that cannot clear costs + safety margin.
  - **Config:** `FIXED_ENTRY_NOTIONAL_USD` (0 or unset = risk-based only); changes versioned in `config_versions` and visible on dashboard/API.
  - **Small accounts:** when fixed notional implies cost drag above guardrail thresholds, required edge and trade-frequency limits from `small_account` mode still apply (costs are % of notional, not account).

### FR-6 Order management & execution
- FR-6.1 Market and limit orders with configurable execution policy; slippage estimated pre-submission from order-book depth.
- FR-6.2 Limit orders have TTL; cancel/replace under controlled rules; no stale orders left indefinitely.
- FR-6.3 Final state confirmed from the exchange (user-data stream + REST query), not the initial response.
- FR-6.4 Emergency stop: close all open positions, disable new orders, alert operator — reachable from dashboard (`POST /controls/emergency-stop`); resume clears estop via `POST /controls/resume` (arm/confirm).

### FR-7 Backtesting
- FR-7.1 Event-driven backtester consuming the same `Strategy` and `RiskEngine` interfaces as paper/live paths.
- FR-7.2 Simulates spread, configurable slippage, fees, partial/missed fills, execution delay, Binance filters; no fills at candle extremes; no look-ahead.
- FR-7.3 Walk-forward testing; baselines: buy-and-hold and no-trade.
- FR-7.4 Report metrics: net/gross return, fees, slippage, max drawdown, Sharpe, Sortino, profit factor, win rate, avg win/loss, expectancy, trade count, exposure time, consecutive losses, VaR (with limitations noted), performance by regime/pair/month, sensitivity to higher fees and slippage.

### FR-8 Paper trading
- FR-8.1 Simulator fills against live market data with the same cost model as backtesting; persistent paper account.
- FR-8.2 Identical daily workflow to live mode (see FR-11).
- FR-8.3 **Testnet learning path:** `EXECUTION_MODE=testnet` uses real testnet order submission with operator-configured fixed entry notional (FR-5.4); paper balance settings do not apply — testnet exchange balance is source of truth, reconciled on startup (FR-2.8).

### FR-9 Machine learning (Phase 5, gated)
- FR-9.1 Experimentation framework: GBDT, logistic regression baseline, random forests, time-series classification, regime detection, volatility forecasting, anomaly detection.
- FR-9.2 Chronological train/validation/untouched-test splits; walk-forward and rolling-window evaluation; reproducible seeds; feature and model versioning.
- FR-9.3 Model registry: a candidate model is promoted only after beating the deployed model on predefined criteria over out-of-sample data; no direct retraining from the bot's own recent trades without validation.
- FR-9.4 Drift monitoring with alerts; automatic demotion to rule-based baselines on severe drift.
- FR-9.5 Deep learning is deferred until clean data volume and strong classical baselines justify it (small tabular datasets favor GBDTs; DL adds variance, opacity, and overfitting risk without commensurate benefit at this data scale).

### FR-10 Dashboard & notifications
- FR-10.1 Dashboard shows: mode (testnet/paper/live), bot status, connection health, balances, positions, open orders, recent fills, daily/cumulative PnL, drawdown, fees+slippage, strategy status, signal confidence, risk-limit utilization, model version, recent warnings/errors.
- FR-10.2 Controls: start, pause, emergency stop — confirmation dialog + server-side authorization required.
- FR-10.3 Notification service (e.g., Telegram/email/webhook) for alerts listed in FR-12.4.

### FR-11 Daily workflow
1. Health checks (API, WebSocket, DB, time sync) → 2. **Restore account state from DB** → 3. **Reconcile balances/positions/orders** → 4. Evaluate market regime → 5. Select enabled pairs → 6. **Rank opportunities in batch** (all strategies score; top candidate enters) → 7. Estimate costs → 8. Risk validation → 9. Execute qualifying trades only → 10. Manage open positions (strategy exits) → 11. Halt on limits → 12. End-of-day report.
- FR-11.1 EOD report includes: starting/ending equity, realized & unrealized PnL, gross result, fees, slippage, net result, % return, max intraday drawdown, trade count, wins/losses, avg holding time, rejected signals + reasons, **near-miss candidates (FR-4.4)**, open positions, per-strategy performance, model version, config version, infra incidents, risk-limit triggers.
- FR-11.2 No minimum trade count exists anywhere in the system.

### FR-12 Observability & audit
- FR-12.1 Structured JSON logging with secret redaction; correlation IDs across signal → order → fill.
- FR-12.2 Append-only audit records for: market-data decisions, signals, rejections, risk calculations, order requests, exchange responses, fills/fees, position updates, model predictions, config changes, manual actions, emergency stops.
- FR-12.3 Prometheus-style metrics; health endpoints.
- FR-12.4 Alerts: failed orders, repeated API errors, WS disconnects, stale data, reconciliation mismatches, unexpected balances, daily-loss/drawdown limits, abnormal trade frequency, model drift, bot shutdown.

### FR-13 Security
See `threat-model.md`. Highlights: no hard-coded keys; env/secrets manager only; `.env` never committed (`.env.example` placeholders only); withdrawal-disabled, least-privilege API keys; IP allowlisting supported; secret redaction in logs and tracebacks; documented key rotation; separated testnet/live credentials; fail-closed on invalid credentials/permissions; multi-step live-enable gate; emergency switch.

## 2. Non-functional requirements

| ID | Requirement |
|----|-------------|
| NFR-1 | Python 3.12, full type hints, MyPy/Pyright clean, Ruff lint, pre-commit hooks |
| NFR-2 | Pydantic v2 settings/models; SQLAlchemy 2.x + Alembic migrations; async I/O for exchange and API layers |
| NFR-3 | Test coverage: unit, integration, testnet E2E (separate suite), property-based tests for sizing/filter math |
| NFR-4 | Idempotent order submission; DB transactions; distributed lock preventing concurrent bot instances |
| NFR-5 | Safe restart: full reconciliation before trading resumes; graceful shutdown cancels/parks work safely |
| NFR-6 | Clock sync monitoring (NTP + Binance server time) |
| NFR-7 | Signal-to-order internal latency budget: < 500 ms p95 (not HFT; correctness > speed) |
| NFR-8 | DB backups (daily, tested restore); configuration versioning (every config change persisted + hash) |
| NFR-9 | Docker Compose for local dev; CI pipeline (lint, type-check, tests) on every commit |
| NFR-10 | Secure defaults: paper mode, live disabled, conservative risk limits |
| NFR-11 | All timestamps stored UTC; monetary values as `NUMERIC` (never float) in DB, `Decimal` in Python |

## 2.1 Operator learning phase — testnet ($200 equivalent)

> **Scope:** Lahtlk · fixed $10/trade · 1–2 month learning window · real-money intent deferred until graduation (§3).

This phase optimizes for **learning and operational confidence**, not monthly PnL targets. Flat or small loss is an acceptable outcome if feedback loops work.

| ID | Success metric | Target | Counter-metric (failure signal) |
|----|----------------|--------|----------------------------------|
| SM-L1 | Execution mode | `EXECUTION_MODE=testnet` with Binance testnet keys; **not live** | Any live order submission |
| SM-L2 | Account scale | Testnet balance treated as **~$200 USDT equivalent**; `FIXED_ENTRY_NOTIONAL_USD=10` | Position size drifts above $10 without operator change |
| SM-L3 | Learning feedback | Review EOD report ≥ **5 days/week**; near-misses (FR-4.4) explain skips | 14+ consecutive days with zero trades *and* zero near-misses (pipeline may be broken or config too tight) |
| SM-L4 | PnL tolerance | End-of-phase equity **≥ $170** (−15% max) *or* operator ends early with documented learnings | Drawdown > 15% without halt firing, or unexplained balance mismatch |
| SM-L5 | Trade discipline | Bot only enters when cost gate + guardrails pass; operator does **not** override gates to force trades | Manual gate bypass; revenge sizing |
| SM-L6 | Phase duration | **30–60 days** on testnet; extend to 90 only if SM-L3–L5 are met but GC-4 not yet | Declaring "ready for live" before §3 graduation criteria |

**Pairs:** BTCUSDT + ETHUSDT only during learning phase.

**Exit ramp:** After SM-L6 + §3 graduation criteria met → consider live with same $10 cap (Phase 6 gate still applies).

## 3. Paper-trading graduation criteria (gate to *considering* live)

All must be true; passing implies no future-profit guarantee.

| # | Criterion | Default threshold (configurable) |
|---|-----------|----------------------------------|
| GC-1 | Historical backtest span | ≥ 2 years per traded pair, incl. ≥ 3 distinct regimes (trend up, trend down, range) |
| GC-2 | Paper-trading duration | ≥ 90 consecutive days on live data |
| GC-3 | Paper trade count | ≥ 100 closed trades |
| GC-4 | Net expectancy | > 0 after fees + conservative slippage, in paper AND walk-forward backtests |
| GC-5 | Max drawdown (paper) | ≤ 15% of paper equity |
| GC-6 | Stability | Positive net result in ≥ 2 of 3 consecutive 30-day paper windows |
| GC-7 | Defects | Zero unresolved critical/high defects |
| GC-8 | Ops drills passed | Restart+reconciliation, API-disconnect, duplicate-order prevention, emergency stop |
| GC-9 | Security review | Secret-management review passed; checklist in threat-model.md |
| GC-10 | Manual approval | Explicit sign-off by system owner, recorded in audit log |

## 4. Acceptance criteria — Phase 1 (this phase)

- [x] Assumptions, goals, non-goals documented (`brief.md`)
- [x] Functional + non-functional requirements (this document)
- [x] Threat model (`threat-model.md`)
- [x] Risk policy with limits and prohibited behaviors (`risk-policy.md`)
- [x] Architecture diagram (Mermaid), component responsibilities, folder structure (`architecture.md`)
- [x] Database design (`database-schema.md`)
- [x] API design (`architecture.md` §6)
- [x] Roadmap with per-phase acceptance criteria (`roadmap.md`)
- [x] Assumed decisions listed for owner review (`roadmap.md` §7)

> **Note:** Phase 1 acceptance covers **documentation deliverables**. Runtime implementation status is tracked separately in §5.

## 5. Implementation status (2026-08-02)

Legend: **Done** · **Partial** · **Deferred** (Phase 6+) · **Blocked**

| Area | Status | Notes |
|------|--------|-------|
| FR-1 Market data | Partial | Kline WS + REST backfill + Redis tick cache + trade/depth WS streams done; per-pair staleness flags deferred |
| FR-2 Exchange | Partial | Testnet adapter done; startup reconciliation done; user-data stream deferred |
| FR-3 Strategies | Done | Five baselines + ranked batch entry path (`docs/spec-v2`) |
| FR-4 Risk | Done | Full veto pipeline; Redis-backed halt + `POST /controls/clear-halt`; FR-4.4 near-miss transparency |
| FR-5–6 Orders | Partial | Maker limit (paper); testnet market-only; estop resume fixed; **FR-5.4 fixed notional Done** |
| FR-7 Backtest | Done | Event-driven; walk-forward; metrics |
| FR-8 Paper | Done | Persistent account restored from DB on restart |
| FR-9 ML | Partial | Registry/promotion/inference done; runtime drift demotion deferred |
| FR-10 Dashboard | Partial | Core panels + controls; model version display deferred |
| FR-11 Workflow | Partial | Ranked batch replaces per-strategy entries (step 6); reconciliation at startup |
| FR-12 Observability | Partial | `/metrics` Prometheus endpoint; correlation IDs partial |
| FR-13 Security | Done | Fail-closed defaults; live structurally **Blocked** until Phase 6 |
| NFR-4 | Done | Redis distributed trader lock |
| NFR-8 | Done | `config_versions` written on startup and session changes |
| Live trading | **Blocked** | No live broker; CLI refuses `mode=live` by design |

### Additional shipped scope (not in original FR list)

- **Ranked batch execution** — entries via `DecisionScorer` + `rank_opportunities`; strategies exit-only
- **Analysis-only mode** — `EXECUTION_MODE=analysis` runs pipeline without orders
- **AI trading assistant** — optional dashboard panel (`ANTHROPIC_API_KEY`)
- **Pair screener / auto-manage** — discovery and enable/disable workflows
- **Session / profit-target policy** — trading hours and daily target protection
- **Demo pulse strategy** — `cryptobot trade --demo` for pipeline smoke tests
