# Project Brief — CryptoBot

> BMAD Phase: **Analyst → Project Brief** (input to PRD and Architecture)
> Status: Draft v1.0 · 2026-08-01 · Owner: Lahiru Thennakoon

---

## 1. Honest framing (read first)

**Guaranteed profit is impossible.** No trading system — rule-based or ML-driven — can always win or produce reliable daily profits in a volatile, adversarial, fee-laden market. This project does **not** attempt that.

The actual objective is a disciplined, data-driven trading system that:

- Attempts positive **long-term risk-adjusted** returns, not daily wins.
- Protects capital before seeking profit.
- Accounts for fees, spread, slippage, latency, and execution risk in every decision.
- Treats **"no trade" as a valid and often preferable decision**.
- Stops automatically when risk limits are hit.
- Never hides losses or manufactures unrealistic performance results.
- Communicates clearly that losing days, weeks, and months are expected.

## 2. Problem statement

Retail crypto bots typically fail for predictable reasons: they ignore transaction costs, overfit backtests, use martingale-style loss recovery, lack risk authority over strategies, and have no operational safety (reconciliation, idempotency, kill switches). CryptoBot exists to build the opposite: an engineering-first platform where risk management and cost modeling have veto power over every signal, and where live trading is structurally impossible until objective graduation criteria are met.

## 3. Goals

| # | Goal | Measure |
|---|------|---------|
| G1 | Safe-by-default platform on Binance **Spot Testnet** + paper trading | Live trading disabled by default; multi-step gate to enable |
| G2 | Realistic backtesting | Event-driven, cost-aware, walk-forward; results vs buy-and-hold and no-trade baselines |
| G3 | Transparent baseline strategies before ML | 5 rule-based strategies with defined entry/exit/stop/regime rules |
| G4 | Risk engine with absolute veto authority | Every signal passes risk validation; limits halt trading automatically |
| G5 | Full auditability | Every signal, rejection, order, fill, fee, and config change persisted |
| G6 | Controlled ML experimentation | Chronological validation, model registry, promotion gates, drift monitoring |

## 4. Non-goals (explicitly out of scope)

- Futures, margin, leverage, borrowing, shorting.
- Withdrawal capability of any kind (the API key must never have it).
- High-frequency / latency-arbitrage trading.
- Guaranteed returns, profit targets, or "daily income" behavior.
- Martingale, doubling-down, unbounded averaging, unbounded grids, revenge trading.
- Multi-exchange trading at launch (adapter interface prepared, only Binance implemented).
- Financial advice. This is experimental decision-support and execution software for its owner.

## 5. Users

Single operator (system owner). No multi-tenant support in v1. Dashboard access is authenticated; high-risk actions require confirmation and server-side authorization.

## 6. Initial trading scope

- Binance **Spot** only, via Spot Testnet (`testnet.binance.vision`) and an internal paper simulator.
- Configurable liquid pairs, initially `BTC/USDT`, `ETH/USDT`.
- Market + limit orders, configurable execution policy.
- Python 3.12, PostgreSQL, Redis (only where justified: caching, queues, distributed locks), FastAPI, Docker Compose, React/Next.js dashboard.

## 7. Operating modes

| Mode | Data | Execution | Default |
|------|------|-----------|---------|
| `backtest` | Historical | Simulated | — |
| `paper` | Live market data | Internal simulator | ✅ default |
| `testnet` | Live testnet data | Binance Spot Testnet | opt-in |
| `live` | Live | Binance Spot | **Disabled**; requires multi-step gate (see risk-policy.md §9) |

## 8. Key assumptions

A1. Binance Spot Testnet remains available and resets periodically (state must survive testnet resets via reconciliation).
A2. Testnet liquidity/prices are unrealistic; testnet validates *integration*, paper trading with live data validates *strategy behavior*; only backtests + paper results count as performance evidence.
A3. Kline/trade/depth data from Binance WebSocket streams is the primary market data source; REST for snapshots and account ops.
A4. Single-region, single-instance deployment initially; distributed locking guards against accidental double-instance runs.
A5. Owner is responsible for verifying Binance availability, local law, tax, and regulatory obligations in their jurisdiction before any deployment.
A6. Capital allocation, if live trading is ever approved, starts very small and is configured explicitly.

## 9. Risks to the project itself

- **Overfitting** — mitigated by untouched test periods, walk-forward validation, cost-sensitivity analysis.
- **Silent integration bugs** — mitigated by reconciliation, idempotent orders, testnet E2E suites.
- **Scope creep toward "make it win"** — mitigated by this brief: expectancy after costs, drawdown, and risk-adjusted metrics are the acceptance basis, never win rate alone.

## 10. Disclaimer (must appear in README and dashboard)

> Cryptocurrency trading is highly risky. No strategy or model guarantees profit. Historical performance does not guarantee future performance. You may lose some or all allocated capital. Verify Binance availability, local laws, tax obligations, and regulatory requirements before deployment. This software is an experimental decision-support and execution system, not a guaranteed income product.

## 11. Related documents

- `prd.md` — functional & non-functional requirements, graduation criteria
- `architecture.md` — components, folder structure, API design
- `database-schema.md` — persistent data model
- `risk-policy.md` — limits, prohibited behaviors, cost model, live gate
- `threat-model.md` — security threat model and controls
- `roadmap.md` — Phases 1–6 with acceptance criteria
