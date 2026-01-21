# Changelog

All notable changes to Pocketwatcher will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
