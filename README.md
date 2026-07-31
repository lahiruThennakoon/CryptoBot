# CryptoBot

Disciplined, risk-first cryptocurrency trading platform for Binance **Spot Testnet and paper trading**. Live trading is disabled by default and structurally gated.

> ## ⚠️ Disclaimer
> Cryptocurrency trading is highly risky. **No strategy or model guarantees profits.** Historical performance does not guarantee future performance. You may lose some or all allocated capital. Loss-making days and periods are expected and normal. Verify Binance availability, local laws, tax obligations, and regulatory requirements before any deployment. This software is an experimental decision-support and execution system — **not** a guaranteed income product.

## Status

**All six phases implemented.** Live trading remains disabled and structurally gated — enabling it requires the full decision package in `docs/live-readiness/` (checklists, drills, performance evidence per the graduation criteria, and owner sign-off in `approval.md`), plus the multi-step configuration gate. `cryptobot readiness` runs the automated review; it can conclude at most "ready for owner review", never "go live".

**Phase 6 — Live-readiness review (implemented).** Automated readiness checker (`cryptobot readiness`), security & reliability checklists with drill procedures, performance-evidence requirements, known limitations & unresolved risks, deployment & rollback procedures, and the owner approval checklist.

**Phase 5 — Machine learning (implemented).** Versioned leakage-safe feature pipeline, embargoed chronological splits, seeded training (pure-Python logistic-regression baseline always available; GBDT/random forest via `pip install -e ".[ml]"`), statistical + after-cost economic evaluation, file-based model registry, champion/challenger promotion gates, and PSI drift detection. Run: `cryptobot ml-train --symbol BTCUSDT --interval 1h`. Models are never promoted from live results and never retrained from the bot's own trades without validation.

**Phase 4 — Paper trading (implemented).** All previous phases plus: real-time paper-trading runtime (live candles → strategies → cost gate → risk veto → paper fills → position protection), Telegram/webhook notifications, daily reports, an authenticated API with two-step-confirmed controls (pause / resume / emergency stop), and a Next.js dashboard. See `docs/roadmap.md` for exit criteria.

```bash
cryptobot import-history --symbol BTCUSDT --interval 1h --days 730
cryptobot backtest --strategy ma_trend --symbol BTCUSDT --interval 1h --walk-forward --sensitivity
cryptobot trade                        # paper-trading runtime (never live)

cd dashboard && cp .env.local.example .env.local && npm install && npm run dev
# → http://localhost:3000 (single-operator UI; keep it on localhost/VPN)
```

## Start everything with one command

```powershell
cd C:\Users\lahtlk\Claude\Projects\CryptoBot
.\start.ps1
```

It checks prerequisites, creates `.env` if missing, generates and syncs the API
token, starts PostgreSQL + Redis, installs dependencies, applies migrations,
runs diagnostics, opens four service windows (API, market data, paper trader,
dashboard) and launches the browser. Paper mode only — live trading is not
reachable from this script.

### Just want to watch it trade?

```powershell
.\demo.ps1
```

Starts the whole stack, seeds 1-minute candles and runs `demo_pulse` — a
strategy that trades every few minutes **on purpose** so you can see fills,
positions, stops and the fee arithmetic happen live. It has no edge, loses
small simulated amounts to costs, and its results are never graduation
evidence. Return to the selective strategies with `cryptobot trade`.

```powershell
.\start.ps1 -NoTrader      # analysis only, no simulated orders
.\start.ps1 -Reinstall     # rebuild python + node dependencies
.\start.ps1 -SkipDocker    # you run postgres/redis yourself
.\stop.ps1                 # stop the app windows
.\stop.ps1 -All            # also stop the containers
```

## Something looks empty or broken?

```powershell
cd backend; .\.venv\Scripts\activate
cryptobot doctor        # tells you exactly what's missing and the command to fix it
```

The most common cause after pulling new features is **missing database tables**:

```powershell
alembic revision --autogenerate -m "new tables"
alembic upgrade head
# then RESTART uvicorn so the new API routes load
```

## Quickstart (development)

```bash
# 1. Configure (never commit .env)
cp .env.example .env        # add your Testnet keys from https://testnet.binance.vision

# 2. Install
cd backend && pip install -e ".[dev]"

# 3. Quality gates
ruff check src tests && mypy && pytest           # unit + property tests
pytest -m testnet                                # real Testnet E2E (opt-in, needs keys)

# 4. Run
docker compose up -d postgres redis
alembic revision --autogenerate -m "initial" && alembic upgrade head
cryptobot check              # connectivity, time sync, permissions, symbol rules
cryptobot collect            # market-data collector
uvicorn cryptobot.api.main:app   # health/status API
```

## Documentation (BMAD)

| Doc | Content |
|-----|---------|
| [docs/brief.md](docs/brief.md) | Project brief: honest objective, goals, non-goals, assumptions |
| [docs/prd.md](docs/prd.md) | Functional & non-functional requirements, graduation criteria |
| [docs/architecture.md](docs/architecture.md) | System diagram, components, folder structure, API design, ADRs |
| [docs/database-schema.md](docs/database-schema.md) | PostgreSQL data model |
| [docs/risk-policy.md](docs/risk-policy.md) | Risk limits, prohibited behaviors, cost gate, live-trading gate |
| [docs/threat-model.md](docs/threat-model.md) | STRIDE threat model, security checklist |
| [docs/roadmap.md](docs/roadmap.md) | Phases 1–6, acceptance criteria, assumed decisions |

## Principles

Capital protection before profit · "no trade" is a valid decision · every decision accounts for fees, spread, slippage, and latency · risk engine can veto anything · automatic halt on limits · full audit trail · no martingale, no leverage, no withdrawal permission, ever.

## Security

Copy `.env.example` → `.env` (never committed). API keys: withdrawals disabled, least privilege, IP allowlisted. Testnet and live credentials are separate. See `docs/threat-model.md`.
