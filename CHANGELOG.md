# Changelog

All notable changes to Pocketwatcher will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-02-05

### Fixed
- **Bug A: Pending claim silent drops** - `_claim_pending_messages()` was ACKing claimed messages without processing them. Now properly processes claimed messages through the batch pipeline before ACKing.
- **Bug B: first_seen loop variable** - `wallet:first_seen` write was outside the counter update loop, causing NameError when `_counter_updates` was empty (blocking ACK) and only writing first_seen for last wallet. Moved inside loop with deduplication.

### Added
- **Multi-process mode**: CLI flags for running components in separate OS processes to bypass GIL
  - `--ingest-only` - Run only Yellowstone → Redis stream ingest
  - `--consume-only` - Run only stream consumer/processor
  - `--detect-only` - Run only detection/alerts loop
  - `--consumer-name` - Set custom consumer name for XREADGROUP
  - `CONSUMER_NAME` env var support for consumer naming
  - No flags = current behavior (backward compatible)
- **hiredis**: Added to requirements for C-based Redis RESP parsing (auto-detected by redis-py)

### Changed
- Consumer names now include hostname and PID for multi-process debugging (`parser-{hostname}-{pid}`)
- Pipeline command count now includes first_seen writes

## [0.2.9] - 2026-02-03

### Fixed
- **Batch consumer deadlock resolved**: Multiple issues caused frozen swap counts
  - Defensive proto parsing in `main.py` - uses `getattr()` to handle malformed transactions
  - Signature normalization in `batch_consumer.py` - falls back to `id:<msg_id>` when signature is "unknown" to prevent dedup collapse
  - Delta log cleanup skips currently-open file to avoid Windows lock errors
  - Batch processor uses function-local pending lists instead of instance state

## [0.2.8] - 2026-02-03

### Added
- **High-throughput mode**: Redis pipelining for 250x throughput improvement
  - `BatchConsumer` and `MultiBatchConsumer` - batched stream consumption with Redis pipelining
  - `BatchProcessor` - processes transaction batches with minimal Redis RTTs
  - `TTLCache` and `HotTokenCache` - local caching to reduce Redis round-trips
  - Dedup, backpressure, and counter updates now pipelined per batch
  - **Measured throughput: 181.1 tx/s** (up from 0.7 tx/s in legacy mode)
  - Counter writes verified working with pipelined batch execution
- `--legacy` CLI flag to use original consumer if needed

### Changed
- Default consumer mode is now high-throughput (batched pipelining)
- Stream consumer batch size increased to 512 for better pipelining efficiency

### Known Issues
- Stats loop may block during maintenance with many active mints (1000+)
  - `cleanup_inactive` makes many Redis calls per mint
  - Processing continues normally, only stats logging is delayed

## [0.2.7] - 2026-02-03

### Added
- **Production hardening**: Security and observability improvements
  - API default bind changed to `127.0.0.1` (localhost only)
  - Optional `API_TOKEN` authentication for write endpoints (PUT/POST/DELETE)
  - Prometheus `/metrics` endpoint for monitoring
- **ALT cache TTL**: Cache entries now expire after 1 hour to prevent stale data
- **Database indexes**: Added indexes for dashboard query performance
  - `idx_alerts_created_at` for time-based alert queries
  - `idx_swap_events_block_time` for swap count queries
- **CI workflow**: GitHub Actions workflow for lint, test, and frontend build
- **Production runbook**: `docs/RUNBOOK.md` with start/stop/backup/restore procedures
- **Alembic database migrations**: Versioned schema changes with async PostgreSQL support
  - Initial migration captures existing schema
  - `alembic upgrade head` for new deployments
- **Windows service management**: NSSM-based Windows services
  - `scripts/windows/install-services.ps1` - Install worker and API services
  - `scripts/windows/manage-services.ps1` - Start/stop/restart/status
  - `scripts/windows/backup.ps1` - Automated PostgreSQL and Redis backup
- **Test coverage**: Unit and integration tests
  - `test_alerting.py` - AlertFormatter tests (Discord embed, Telegram, risk levels)
  - `test_integration.py` - Discord retry, pending message claiming, graceful shutdown
- **Static file serving**: API server serves built frontend from `web/dist`
  - SPA routing support for client-side routes

### Changed
- API server now reads host/port from `API_HOST`/`API_PORT` env vars
- pyproject.toml version aligned with CHANGELOG
- **CTO scoring enhanced**: Uses both in-memory union-find and historical postgres cluster_id data
- **Vite production build**: Vendor chunk splitting and terser minification

### Fixed
- **block_time handling**: Uses current timestamp instead of 0 (Yellowstone gRPC doesn't include block_time)

## [0.2.6] - 2026-02-03

### Added
- **Discord retry with exponential backoff**: Alerts now retry on network errors and 5xx responses
  - Delays: 1s, 2s, 4s between attempts (max 3 attempts)
  - 4xx errors (except 429 rate limit) fail immediately
- **Pending message recovery on restart**: Stream consumer now claims unACKed messages from previous runs
  - Messages idle > 30s are reclaimed and processed
  - Ensures no alert loss on crash/restart

### Fixed
- **Windows signal handling**: Graceful shutdown now works on Windows
  - Uses `signal.signal()` instead of `loop.add_signal_handler()`
  - Handles SIGINT, SIGTERM, and SIGBREAK (Windows Ctrl+Break)

## [0.2.5] - 2026-01-24

### Added
- **Backtest Dashboard**: New `/backtest` page showing alert performance over time
  - Summary stats: total alerts, win rate, average gain, best/worst performers
  - Trigger leaderboard: performance breakdown by trigger type with win rates
  - Results table: all alerts with current mcap, gain %, and status (winner/loser/dead)
  - Time range selector (24h, 7d, 30d)
  - Background cache refresh every 5 minutes for fast page loads
- **API endpoints**:
  - `GET /api/backtest?hours=24` - get cached backtest results
  - `POST /api/backtest/refresh` - force cache refresh
- **Redis caching**: Token price and backtest result caching to reduce API calls

## [0.2.4] - 2026-01-24

### Changed
- **Improved win rate via trigger tuning**: Based on backtest analysis
  - Disabled `gradual_accumulation` - 36% win rate, -55% avg gain
  - Disabled `sybil_pattern` - 0% win rate in backtest
  - Tightened `extreme_ratio` - raised from 3→10 SOL volume, 5→10 buys, added 3+ unique buyers
- **Added minimum mcap filter**: Tokens below 500 SOL mcap (~$60K) are now skipped
  - Prevents alerts on micro-cap tokens that almost always rug

## [0.2.3] - 2026-01-24

### Added
- **Calendar View**: New dashboard page showing alerts grouped by date
  - Visual calendar with color-coded days based on alert count
  - Click any day to see all alerts for that date
  - Summary stats (total alerts, tokens flagged, active days)
  - Date range selector (7d, 14d, 30d, 60d)
- **API endpoint `/api/alerts/by-date`**: Returns alerts grouped by date for calendar view

## [0.2.2] - 2026-01-23

### Added
- **DexScreener client**: New `DexScreenerClient` as primary price data source
  - Free API, no authentication required
  - Gets price, market cap, liquidity, volume, and price change data
  - Used by backtest and daily_report scripts

### Changed
- **Replaced GMGN with DexScreener**: GMGN has Cloudflare protection that expires frequently
  - `scripts/gmgn_client.py` now exports `DexScreenerClient` as primary client
  - `GMGNClient` still available but likely to fail due to Cloudflare
  - `scripts/daily_report.py` now uses DexScreener
  - `scripts/backtest.py` already used DexScreener

## [0.2.1] - 2026-01-21

### Added
- **Market cap tracking in alerts**: Critical trading info now displayed in dashboard
  - `mcap_sol` - Market cap at alert time
  - `avg_entry_mcap` - Average entry mcap of top buyers (when they started accumulating)
  - Prominently displayed in AlertList component
- **Helius DAS API fallback**: Gets token metadata for new tokens not yet on DexScreener
  - Uses getAsset method to fetch on-chain Metaplex metadata
  - Works for newly launched pump.fun tokens

### Changed
- **Market caps now displayed in USD**: Converted from SOL-denominated to USD values
  - Frontend fetches SOL/USD price from CoinGecko API (cached 60s)
  - Discord alerts also convert to USD using real-time price
  - Format: "$1.2M", "$50K", "$500" instead of "1.2M SOL"
  - Cleaner display without redundant labels

### Fixed
- **Market cap timing issue**: Now calculates and stores mcap for ALL swaps (not just HOT tokens)
  - Mcap is cached in Redis and available immediately at alert creation time
  - Previously mcap was null because postgres swaps weren't backfilled yet
- **Token metadata null values**: Added DAS API fallback for tokens without DexScreener data

## [0.2.0] - 2026-01-20

### Added
- **Web Configuration Dashboard**: React dashboard for live configuration without restarts
  - Real-time stats display (tx/s, HOT tokens, alerts, lag, mode)
  - HOT tokens panel with live stats
  - Recent alerts list with links to Solscan
  - Health status indicator
- **Trigger Editor**: Visual trigger configuration
  - Add, edit, and delete triggers
  - Enable/disable individual triggers
  - Validation with helpful error messages
  - Hot-reload on save (no restart required)
- **Settings Panel**: Configure alert channels and detection parameters
  - Discord webhook URL
  - Telegram bot token and chat ID
  - Backpressure thresholds (lag, stream length)
  - Detection parameters (HOT TTL, cooldown, confidence)
- **FastAPI Backend**: Configuration API at port 8080
  - `GET/PUT /api/triggers` - Trigger CRUD
  - `POST /api/triggers/validate` - Validate config
  - `POST /api/triggers/reset` - Reset to file defaults
  - `GET/PUT /api/settings` - Settings CRUD
  - `GET /api/stats` - Real-time stats
  - `GET /api/alerts` - Alert history
  - `GET /api/health` - Health check
  - `GET /api/hot-tokens` - Active HOT tokens
- **Hot-Reload for TriggerEvaluator**: Subscribes to Redis pub/sub for instant config updates
  - Atomic trigger list replacement
  - No restart required for trigger changes

### Changed
- TriggerEvaluator now accepts optional redis_client for hot-reload support
- Added fastapi and uvicorn to requirements.txt

## [0.1.5] - 2026-01-20

### Added
- **Venue display in alerts**: Shows which DEX (pump.fun, Jupiter, Raydium, etc) with emoji badges
- **Token metadata from DexScreener**: Fetches name, symbol, and image for tokens
- **Token images**: Discord embeds now show token thumbnails when available

### Changed
- **Tighter trigger thresholds**: All triggers now require minimum volume to reduce noise
  - `extreme_ratio`: Now requires ≥3 SOL volume and ≥5 buys
  - `whale_concentration`: Now requires ≥10 SOL volume, ≥10 buys, and 80% concentration (was 60%)
  - All other triggers also have volume minimums

### Fixed
- **Token image always fetched**: DexScreener is now always queried for image, not just when name/symbol missing
- **Database migration**: Added venue and token_image columns to alerts table

### Removed
- Supply display removed from alerts (was showing "1.0B tokens" which is not useful)

## [0.1.4] - 2026-01-20

### Added
- **Market cap tracking at swap time**: Each swap event now records the market cap at the time of the swap
  - New `mcap_at_swap` column in swap_events table
  - Calculated from swap price × token supply for accurate historical tracking
- **Average entry mcap for top buyers**: Discord alerts now show average accumulation market cap for each top buyer
  - Displays per-buyer entry price: "Wallet - 1.5 SOL @ 50K SOL"
  - Shows overall average entry in header: "Top Buyers (85% of volume, avg entry @ 45K SOL)"
- **Alert format improvements**: Ticker + metadata shown first, risk communicated via color/emoji only

## [0.1.3] - 2026-01-20

### Added
- **Market cap tracking at alert time**: Alerts now capture price_sol, mcap_sol, and token_supply at the moment they fire
  - Token supply fetched via Helius getAccountInfo (1 credit per call)
  - Price calculated from postgres swaps if available (may be NULL at alert time due to async backfill)
  - Database schema updated with new columns
- **Daily report script**: `scripts/daily_report.py` generates performance reports comparing alert-time values with current prices
- **GMGN client**: `scripts/gmgn_client.py` for fetching current token prices from GMGN (adapted from sauron)

### Fixed
- **Detection loop not creating alerts**: Fixed main.py detection loop to call `_handle_trigger_result` instead of just logging trigger results
- **Price calculation blocking**: Replaced slow delta_log scanning with fast rolling counter + postgres query with 2s timeout

## [0.1.2] - 2026-01-20

### Fixed
- **Swap metrics not counting**: Fixed metrics summary to sum counters across all label sets - swaps_detected now reflects real activity instead of 0
- **Stale health checks**: Backpressure updates now write processing lag + stream length into gauges per tx, health checker refreshes stream length from Redis
- **Duplicate swap processing**: Swap processing now called once per inferred swap (not once per mint touched), fixing inflated counters and trigger noise

### Added
- **Multi-consumer support**: Configurable STREAM_CONSUMER_COUNT to scale throughput and reduce backlog growth

## [0.1.1] - 2026-01-20

### Fixed
- **Recursion error in EventLog**: Fixed circular call between `_get_file()` and `_flush_buffer()` that caused maximum recursion depth exceeded errors during log rotation
- **CTOScore attribute error**: Fixed alert formatter accessing non-existent `component_scores` attribute - now correctly builds component scores dict from individual attributes
- **Set iteration error**: Fixed potential "set changed size during iteration" error in StateManager by copying dict values before iteration
- **Yellowstone authentication**: Confirmed correct x-token authentication format for Chainstack Yellowstone gRPC

## [0.1.0] - 2025-01-20

### Added
- Initial implementation of Pocketwatcher MVP v0
- **Stream Module**: Yellowstone gRPC client for live transaction streaming
  - Redis Streams buffer for crash-safe ingestion
  - Signature deduplication with SET NX EX
  - Program filter for MVP program set (pump.fun, Jupiter v6, Raydium, Orca, Meteora)
- **Parser Module**: Balance delta extraction and swap inference
  - Pre/post token balance delta calculation
  - SOL/WSOL/fee/rent handling
  - Swap inference with confidence scoring (target: 70-90% detection rate)
  - ALT (Address Lookup Table) cache for Jupiter v6 transactions
- **Detection Module**: Rolling counters and trigger evaluation
  - Redis bucketed counters for 5m and 1h windows
  - HyperLogLog for unique buyer/seller tracking
  - Configurable trigger thresholds (concentration, stealth, sybil, whale patterns)
  - HOT/WARM/COLD token state machine
- **Enrichment Module**: Wallet analysis and clustering
  - Helius API client with daily credit budget management
  - Wallet funding trace (1-2 hops)
  - Union-find wallet clustering
  - CTO (Cabal/Team/Organization) likelihood scoring
- **Alerting Module**: Discord and Telegram notifications
  - Rich Discord embeds with token stats and evidence
  - Telegram markdown messages with links
  - Rate limiting and retry logic
- **Storage**: Redis + PostgreSQL + local logs
  - Redis Streams for ingest buffer
  - Redis for rolling counters and HOT token tracking
  - PostgreSQL for token profiles, swap events, alerts
  - Append-only logs for MintTouchedEvent (permanent) and TxDeltaRecord (60 min retention)
- **Backpressure Management**: Graceful degradation under load
  - NORMAL/DEGRADED/CRITICAL modes based on lag and queue depth
  - Automatic mode transitions with logging
- **Monitoring**: Metrics collection and health checking
  - Counters, gauges, and histograms
  - Periodic health checks with issue detection
- Configuration via environment variables and YAML files
- Mock stream client for testing without Yellowstone connection

### Technical Details
- Python 3.10+ required
- Async-first architecture with asyncio
- gRPC for Yellowstone streaming
- msgpack + zlib for efficient log serialization
