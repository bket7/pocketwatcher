# Pocketwatcher Architecture

## Overview

Pocketwatcher is a Solana CTO (Cabal/Team/Organization) and stealth-accumulation monitor. It streams transactions in real-time, detects suspicious trading patterns on meme coins, enriches data with wallet analysis, and sends alerts.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        SINGLE PYTHON APP                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. STREAM READER                                                │
│     └─ Yellowstone gRPC → transactions filter (all program IDs) │
│     └─ Immediately push to Redis Streams (stream:tx) w/ maxlen  │
│                    │                                             │
│                    ▼                                             │
│  2. PARSER (reads from Redis Streams)                            │
│     ├─ Dedup: SET sig:{signature} 1 EX 600 NX                   │
│     ├─ Build deltas from pre/post token balances                │
│     ├─ ALWAYS emit MintTouchedEvent + TxDeltaRecord             │
│     ├─ If confidence >= 0.7: emit SwapEventFull                 │
│     └─ Write to:                                                 │
│        ├─ Redis bucketed counters (1m/5m windows)               │
│        ├─ Append-only TxDeltaRecord log (60 min retention)      │
│        └─ SwapEventFull to Postgres (HOT/WARM only)             │
│                    │                                             │
│                    ▼                                             │
│  3. DETECTOR + HOT MANAGER                                       │
│     ├─ Every second: evaluate tokens with activity              │
│     ├─ If trigger → mark HOT (Redis set + expiry)               │
│     ├─ Backfill: re-parse TxDeltaRecords for HOT token          │
│     └─ Push enrichment jobs to async queue                      │
│                    │                                             │
│                    ▼                                             │
│  4. ENRICHER                                                     │
│     ├─ Pull top buyers from recent SwapEventFull                │
│     ├─ Helius calls with semaphore + daily credit bucket        │
│     ├─ Update WalletProfile + cluster (union-find)              │
│     └─ Emit alert to Discord + Telegram                         │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Core Principles

1. **Never drop coverage** - Only drop detail under pressure
2. **Durable buffering** - Redis Streams survive crashes
3. **Balance-delta inference** - Parse swaps from balance changes, not instruction data
4. **Hot/Warm/Cold states** - Progressive detail based on token interest
5. **Credit budget** - Daily Helius credit cap prevents overspending

## Module Structure

```
pocketwatcher/
├── main.py                    # Application entry point
├── config/
│   ├── programs.yaml          # Program IDs to filter
│   ├── thresholds.yaml        # Detection triggers
│   └── settings.py            # Pydantic settings
├── stream/
│   ├── yellowstone.py         # Yellowstone gRPC client
│   ├── consumer.py            # Redis Streams consumer
│   └── dedup.py               # Signature deduplication
├── parser/
│   ├── deltas.py              # Balance delta extraction
│   ├── inference.py           # Swap inference algorithm
│   └── alt_cache.py           # ALT resolution
├── detection/
│   ├── counters.py            # Redis rolling counters
│   ├── state.py               # HOT/WARM/COLD machine
│   └── triggers.py            # Threshold evaluation
├── enrichment/
│   ├── helius.py              # Helius client + credit bucket
│   ├── clustering.py          # Union-find wallet clusters
│   └── scoring.py             # CTO likelihood
├── alerting/
│   ├── discord.py
│   ├── telegram.py
│   └── formatter.py
├── storage/
│   ├── redis_client.py
│   ├── postgres_client.py
│   ├── delta_log.py           # 60 min retention
│   └── event_log.py           # Permanent
├── core/
│   ├── processor.py           # Main orchestrator
│   ├── backpressure.py        # Degradation management
│   └── monitoring.py          # Metrics collection
├── models/
│   ├── events.py              # Data models
│   └── profiles.py            # Token/Wallet profiles
├── api/
│   ├── server.py              # FastAPI app
│   ├── deps.py                # Shared dependencies
│   ├── models.py              # Pydantic request/response
│   └── routes/
│       ├── triggers.py        # Trigger CRUD
│       ├── settings.py        # Settings CRUD
│       └── stats.py           # Stats & health
├── web/
│   ├── src/
│   │   ├── App.jsx            # Main React app
│   │   ├── api.js             # API client
│   │   ├── components/        # Reusable components
│   │   └── pages/             # Dashboard, Triggers, Settings
│   └── package.json
└── tests/
```

## Data Flow

### Transaction Processing

1. **Ingest**: Yellowstone gRPC streams transactions matching our program filter
2. **Buffer**: Transactions pushed to Redis Stream (crash-safe)
3. **Dedup**: Signature checked with SET NX EX (10 min TTL)
4. **Parse**: Build balance deltas from pre/post balances
5. **Emit**: Always emit MintTouchedEvent + TxDeltaRecord
6. **Infer**: If swap detected with confidence >= 0.7, emit SwapEventFull
7. **Count**: Update Redis rolling counters for the token
8. **Evaluate**: Check if any detection triggers fire
9. **HOT**: If triggered, mark token HOT and backfill from delta log
10. **Enrich**: For HOT tokens, trace wallet funding and cluster
11. **Alert**: Send formatted alert to Discord/Telegram

### State Machine

| State | Storage | Triggers |
|-------|---------|----------|
| COLD | Aggregates only | Default |
| WARM | Per-swap events 30-60 min | First activity |
| HOT | Full enrichment + clustering | Crosses thresholds |

## Storage Strategy

| Data | Storage | TTL |
|------|---------|-----|
| MintTouchedEvent | Append-only log (zstd msgpack) | Forever |
| TxDeltaRecord | Disk append log (zstd msgpack) | 60 min |
| SwapEventFull | Postgres (HOT/WARM only) | 30 days |
| Rolling counters | Redis (bucketed) | Minutes/hours |
| Ingest buffer | Redis Streams (stream:tx) | maxlen cap |
| Token state | Postgres | Forever |
| Alerts | Postgres | Forever |

## Backpressure Management

| Mode | Condition | Action |
|------|-----------|--------|
| NORMAL | lag < 5s, stream < 50k | Full parsing + SwapEventFull |
| DEGRADED | lag 5-30s OR stream 50k-80k | MintTouchedEvent + TxDeltaRecord only |
| CRITICAL | lag > 30s OR stream > 80k | Signature + mints only, pause enrichment |

## External Dependencies

- **Chainstack Yellowstone**: Transaction streaming
- **Redis**: Buffering, dedup, counters
- **PostgreSQL**: Persistent storage
- **Helius**: Wallet enrichment (credit budgeted)
- **Discord/Telegram**: Alert delivery

## Web Configuration Dashboard

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  React Frontend │────▶│  FastAPI Backend │────▶│     Redis       │
│   (port 3001)   │     │   (port 8080)    │     │  cfg:* keys     │
└─────────────────┘     └─────────────────┘     │  pub/sub reload │
                                                 └────────┬────────┘
                                                          │
                                                          ▼
                                                 ┌─────────────────┐
                                                 │  Pocketwatcher  │
                                                 │  (subscribes to │
                                                 │   cfg:reload)   │
                                                 └─────────────────┘
```

### Hot-Reload Flow

1. Frontend sends PUT `/api/triggers` with new config
2. Backend validates config (parse all conditions)
3. Backend stores in Redis: `cfg:thresholds`
4. Backend publishes to `cfg:reload` channel
5. TriggerEvaluator receives notification via pub/sub
6. TriggerEvaluator atomically replaces trigger lists

### API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/triggers` | GET/PUT | Trigger CRUD |
| `/api/triggers/validate` | POST | Validate without saving |
| `/api/triggers/reset` | POST | Reset to file defaults |
| `/api/settings` | GET/PUT | Settings CRUD |
| `/api/stats` | GET | Real-time stats |
| `/api/alerts` | GET | Alert history |
| `/api/health` | GET | Health check |
| `/api/hot-tokens` | GET | Active HOT tokens |

### Hot-Reloadable Settings

| Setting | Redis Key | Notes |
|---------|-----------|-------|
| Trigger thresholds | `cfg:thresholds` | Full YAML config |
| Discord webhook URL | `cfg:alerts` | Alert channels |
| Telegram config | `cfg:alerts` | Alert channels |
| Backpressure thresholds | `cfg:backpressure` | Lag thresholds |
| Detection parameters | `cfg:detection` | HOT TTL, cooldown |

### Requires Restart

- Redis URL
- PostgreSQL URL
- Yellowstone endpoint/token
- Helius API key

## Configuration

All configuration via environment variables (see `.env.example`) or YAML files.

Key settings:
- `YELLOWSTONE_ENDPOINT`: Chainstack gRPC endpoint
- `YELLOWSTONE_TOKEN`: Auth token
- `POSTGRES_URL`: Database connection
- `REDIS_URL`: Redis connection
- `HELIUS_API_KEY`: For wallet enrichment
- `HELIUS_DAILY_CREDIT_LIMIT`: Budget cap
- `DISCORD_WEBHOOK_URL`: Alert destination
- `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`: Alert destination
