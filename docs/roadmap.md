# Development Roadmap — CryptoBot

> Draft v1.0 · 2026-08-01 · Phases are sequential gates; a phase starts only when the previous phase's acceptance criteria are met and reviewed.

## Phase 1 — Product & risk specification ✅ (this delivery)

Deliverables: `brief.md`, `prd.md`, `architecture.md`, `database-schema.md`, `risk-policy.md`, `threat-model.md`, this roadmap, `.env.example`, README with disclaimer.
**Exit criteria:** owner reviews assumed decisions (§7) and approves or amends.

## Phase 2 — Testnet foundation (est. 2–3 weeks)

Scaffolding (pyproject, ruff, mypy, pytest, pre-commit, Docker Compose, CI) · Pydantic config with mode gating · `BinanceSpotAdapter` (testnet) with time sync, rate limiter, backoff+jitter, redaction — all endpoints verified against current official Binance docs · WS market data with staleness detection, reconnect, backfill · SQLAlchemy models + Alembic · exchangeInfo filter validation · paper account · structured logging · health checks · unit/integration/property tests + separate testnet suite.
**Exit criteria:** 72h unattended testnet data collection without gaps or crashes; reconnect and restart-reconciliation drills pass; CI green; zero secrets in logs (tested).

## Phase 3 — Backtesting (est. 2–3 weeks)

Historical importer with validation · event-driven simulator sharing production interfaces · cost model (fees/spread/slippage/partial fills/filters/latency) · 5 baseline strategies · full metric reports vs buy-and-hold and no-trade · walk-forward testing · fee/slippage sensitivity analysis.
**Exit criteria:** backtester passes validation tests (no look-ahead — proven by shuffled-future test; deterministic reruns; costs verifiably applied); ≥2 years of clean data per pair; baseline strategy reports produced and reviewed. *Note: strategies are not required to be profitable to exit Phase 3 — honest measurement is the deliverable.*

## Phase 4 — Paper trading (est. 2–3 weeks)

Real-time signal pipeline · risk engine with full limit set + halt/review flow · paper execution with cost model · position management (stops, take-profit, max holding) · notifications · dashboard with confirmed controls · EOD reports.
**Exit criteria:** 14-day continuous paper run without manual intervention; all risk-limit, duplicate-order, stale-data, and emergency-stop drills pass; EOD reports reconcile to the cent against DB records.

## Phase 5 — Machine learning (est. 3–4 weeks; only after Phase 3/4 data quality validated)

Versioned feature pipeline · training pipeline with chronological splits + walk-forward · model registry with champion/challenger promotion gates · drift detection · controlled promotion (never auto-retrain from own recent trades without validation).
**Exit criteria:** logistic-regression baseline beaten out-of-sample by any promoted model; promotion/demotion drills pass; drift alerts fire on injected drift; all experiments reproducible from seed + versions.

## Phase 6 — Live-readiness review (no automatic live enablement)

Produce: security checklist results (threat-model §3) · reliability checklist (restart, reconciliation, kill-switch, backup/restore drills) · performance evidence (backtest + ≥90-day paper, per prd.md §3) · known limitations · unresolved risks · deployment procedure · rollback procedure · live-trading approval checklist requiring owner sign-off.
**Exit criteria:** this phase produces a *decision package*, not a live system. Live trading remains disabled until every graduation criterion and gate factor (risk-policy §9) is satisfied and the owner explicitly approves.

## 7. Assumed decisions (for owner review — Phase 1 gate)

| # | Decision | Assumed value | Alternatives |
|---|----------|---------------|--------------|
| D1 | Documentation method | BMAD (brief → PRD → architecture), docs in `docs/` | full BMAD agent workflow with sharded epics/stories at Phase 2 |
| D2 | Dashboard framework | Next.js | plain React + Vite |
| D3 | Backend shape | Modular monolith, DI, async | microservices (rejected for v1: ops cost) |
| D4 | Quote currency & pairs | USDT; BTC/USDT, ETH/USDT | BUSD retired; other liquid pairs later |
| D5 | Primary signal timeframes | 1m ingestion; 5m/15m/1h/4h strategy timeframes | tick-level (rejected: not HFT) |
| D6 | Risk defaults | Values in risk-policy.md §1–3 | all configurable; stated as engineering defaults |
| D7 | Type checker | MyPy strict | Pyright |
| D8 | Notifications | Telegram first, plus webhook | email, Slack |
| D9 | Auth | single-operator JWT/session + confirmation tokens | OAuth/SSO (overkill v1) |
| D10 | ML tooling | scikit-learn + LightGBM/XGBoost; MLflow-style local registry | cloud ML platforms (rejected: data control) |
| D11 | Metrics stack | Prometheus + Grafana via Docker Compose | hosted observability |
| D12 | Graduation thresholds | prd.md §3 defaults (90 days, 100 trades, ≤15% DD, etc.) | owner may tighten/loosen before Phase 4 |
| D13 | Monetary precision | NUMERIC(38,18) / Decimal | — |
| D14 | Backtest data source | Binance official kline data (REST + public data dumps) | third-party vendors |
