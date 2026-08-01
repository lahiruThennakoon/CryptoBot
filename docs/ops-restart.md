# Server Restart & Data Persistence

> Ops guide · 2026-08-02  
> Related: `live-readiness/deployment-rollback.md` · `database-schema.md` §3 · PRD NFR-5, NFR-8, FR-2.8, FR-8.1

This document answers: **“The server restarted — did I lose anything?”**

---

## 1. Source of truth

| Layer | Role | Survives trader restart? |
|-------|------|---------------------------|
| **PostgreSQL** (`pgdata` volume) | Positions, orders, fills, equity, signals, EOD reports, candles, audit | **Yes** — if the volume is kept |
| **Binance testnet/live** | Real balances, open orders, fills (testnet/live modes) | **Yes** — independent of your server |
| **Redis** | Tick cache, trader lock | **No** — rebuilt / expires (by design) |
| **Trader process RAM** | Bar buffers, pending flush batch, paper maker limits | **No** — restored or re-seeded on startup |

**Rule:** Postgres + exchange reconciliation = safe restart. **Never** treat Redis as durable.

---

## 2. What is persisted in PostgreSQL

- Open and closed **positions** (qty, entry, stops, PnL)
- **Orders** and **fills** (fees, client order IDs)
- **Equity snapshots** (cash, exposure, high-water mark inputs)
- **Signals** (executed, rejected, near-miss)
- **Daily reports** (EOD content including near-misses)
- **Risk events**, **audit log**, **config_versions**
- Historical **candles**

On startup the trader calls `restore_paper_state` then `reconcile_on_startup` before resuming entries (FR-2.8, NFR-5).

---

## 3. What you may lose (usually harmless)

| Item | Notes |
|------|--------|
| Redis tick cache | Repopulated from WebSocket within seconds |
| In-memory candle warmup | Re-loaded from DB on startup |
| Unflushed signal batch | Sub-second window if process is killed (`SIGKILL`) |
| Paper **pending maker** limits | Not used on testnet (`EXECUTION_MODE=testnet` uses market entries) |
| Redis trader lock | TTL expires; prevents duplicate traders briefly after crash |

---

## 4. When you **do** lose important data

| Action | Result |
|--------|--------|
| `docker compose down -v` | **Wipes `pgdata`** — full bot history gone |
| Deleting the Postgres volume / ephemeral disk | Same as above |
| Restoring a **stale backup** without reconciliation | DB out of sync with exchange — bot **halts** until fixed |
| Running two traders against one account | Blocked by Redis lock; if lock expires, duplicate-instance risk |

Testnet exchange balances and fills **still exist on Binance** even if your DB is wiped — but you must reconcile or re-import state manually.

---

## 5. Safe restart procedure

### Normal restart (deploy, reboot, `docker compose restart`)

```bash
# Prefer graceful stop so pending DB writes flush
docker compose stop trader collector api

# After host reboot or image update
docker compose up -d postgres redis
docker compose run --rm api alembic upgrade head   # if schema changed
docker compose up -d
```

### Verify in logs (trader container)

Look for these lines after startup:

1. `state_restored` — equity, open positions, cash
2. `risk_config_applied` — fixed notional, guardrails
3. `execution_routing` — `mode=testnet` (or paper)
4. **No** `reconciliation_halt` — if present, trading stays halted until review

### Dashboard / API checks

- `GET /api/v1/health` → `ok`
- Overview shows correct **mode** and **equity**
- Open positions match what you expect
- If halted: `POST /controls/clear-halt` **only after** reviewing mismatch detail

---

## 6. Backup (recommended daily)

Docker Compose Postgres (from repo root, adjust password/host as needed):

```bash
# Create backup directory on the server
mkdir -p /var/backups/cryptobot

# Dump (run while postgres is up)
docker compose exec -T postgres pg_dump -U cryptobot -d cryptobot --format=custom \
  -f /tmp/cryptobot.dump

docker compose cp postgres:/tmp/cryptobot.dump \
  "/var/backups/cryptobot/cryptobot-$(date -u +%Y%m%d-%H%M%S).dump"
```

**Plain SQL alternative** (human-readable, larger files):

```bash
docker compose exec -T postgres pg_dump -U cryptobot -d cryptobot \
  > "/var/backups/cryptobot/cryptobot-$(date -u +%Y%m%d).sql"
```

### What backups contain

- All trading history and audit data  
- **No API secrets** — keys live in `.env` only (back up `.env` separately, encrypted)

### Retention suggestion

- Keep 7 daily + 4 weekly dumps  
- Run a **restore drill** monthly (NFR-8): restore to a temp DB → `cryptobot check` → delete temp

---

## 7. Restore from backup

```bash
# Stop writers
docker compose stop trader collector api

# Restore (custom format example)
docker compose cp /var/backups/cryptobot/cryptobot-YYYYMMDD.dump postgres:/tmp/restore.dump
docker compose exec -T postgres pg_restore -U cryptobot -d cryptobot --clean --if-exists /tmp/restore.dump

# Or SQL file
docker compose exec -T postgres psql -U cryptobot -d cryptobot < /path/to/backup.sql

# Start and reconcile — do NOT skip this
docker compose up -d
# Watch trader logs for reconciliation; halt means DB ≠ exchange
```

After any restore: treat as **unsafe to trade** until reconciliation passes.

---

## 8. Testnet learning phase ($200 / $10 trades)

| Concern | Answer |
|---------|--------|
| Server reboot | OK — Postgres volume preserved |
| Testnet USDT balance | On Binance testnet; not lost by reboot |
| Bot position history | In Postgres; restored on startup |
| Near-miss / EOD history | In Postgres (`signals`, `daily_reports`) |
| Fixed $10 setting | In `.env` — ensure `.env` is on the server (not in git) |

---

## 9. Quick checklist (printable)

- [ ] Postgres uses a **named volume** (`pgdata`) or managed DB with backups  
- [ ] Never run `docker compose down -v` on production  
- [ ] Daily `pg_dump` to off-server storage  
- [ ] `.env` backed up separately (encrypted)  
- [ ] After restart: confirm `state_restored` + no `reconciliation_halt`  
- [ ] Monthly restore drill documented in audit log  

---

## 10. Commands to avoid on a live server

```bash
docker compose down -v          # DELETES pgdata
docker volume rm cryptobot_pgdata # DELETES all DB data
rm -rf /var/lib/docker/volumes/ # catastrophic
```

Use `docker compose stop` / `docker compose down` **without** `-v` instead.
