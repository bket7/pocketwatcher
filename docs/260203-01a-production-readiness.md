# Pocketwatcher Production Readiness - Implementation Spec

Version: a
Date: 2026-02-03
Requirements source: PLAN.md, VALIDATION_AND_DEBT.md, CHANGELOG.md, .env.example, requirements.txt, pyproject.toml, docs/ARCHITECTURE.md

## Summary
This plan finishes the remaining production readiness work for Pocketwatcher on a Windows VPS.
It focuses on correctness fixes, test coverage, observability, and deployment hardening with zero alert loss as the target.

## Scope
### In Scope
- Close remaining correctness gaps listed in PLAN.md and VALIDATION_AND_DEBT.md.
- Add P0 tests plus integration tests for retry, shutdown, and pending-claim.
- Add basic production ops: service management, backups, metrics, and private API access.
- Prepare deployment assets and runbook for a single Windows VPS.

### Out of Scope
- New alert channels or detection features.
- Multi-node scalability or cross-region redundancy.
- UI redesign beyond production build and serving.

## Technical Approach
### Architecture
- Single Windows VPS deployment with all services on one host.
- Core services: Pocketwatcher worker, FastAPI config API, PostgreSQL, Redis.
- Services run as Windows services via NSSM with automatic restart.
- API bound to localhost by default and accessed over RDP or SSH tunnel.
- Frontend built as static assets and served by the API or a local static file server.
- Default path avoids Docker Desktop on Windows Server due to lack of support; use native services unless the VPS is Windows 10 or 11.

### Data Model
- Keep existing tables: token_profiles, swap_events, wallet_profiles, alerts.
- Add schema migrations and index changes through a migration tool.
- Configure Redis persistence with both AOF and RDB to minimize alert loss.
- Schedule PostgreSQL backups and verify restore procedure.

### API / Interface
- Keep current endpoints and response shapes.
- Add optional API token authentication via an `API_TOKEN` environment variable for any non-local access.
- Add a `/metrics` endpoint for Prometheus scraping.
- Set default bind host to 127.0.0.1 with explicit override for remote use.

### Dependencies
- Python 3.11+ for runtime consistency.
- PostgreSQL 17.x for production database and backups.
- Redis 7.x with AOF and RDB persistence enabled.
- FastAPI and Uvicorn for the config API.
- Prometheus Python client for `/metrics` endpoint.
- NSSM for Windows service management.
- Node.js LTS for frontend builds and Vite.
- Chainstack Yellowstone gRPC, Helius API, Discord Webhooks, Telegram Bot API, DexScreener API.

Documentation links:
- Docker Desktop on Windows: https://docs.docker.com/desktop/setup/install/windows-install/
- PostgreSQL Windows installer: https://www.postgresql.org/download/windows/
- PostgreSQL 17 docs: https://www.postgresql.org/docs/17/
- Redis docs: https://redis.io/docs/latest/
- Redis persistence: https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/
- NSSM: https://nssm.cc/
- Prometheus Python client: https://prometheus.github.io/client_python/
- GitHub Actions workflow syntax: https://docs.github.com/actions/learn-github-actions/workflow-syntax-for-github-actions
- Chainstack Yellowstone gRPC: https://docs.chainstack.com/docs/yellowstone-grpc-geyser-plugin
- Helius docs: https://www.helius.dev/docs
- Discord webhooks: https://discord.com/developers/docs/resources/webhook
- Telegram Bot API: https://core.telegram.org/bots/api
- DexScreener docs: https://docs.dexscreener.com/

## Implementation Steps
1. Confirm Windows edition and virtualization support; decide between native services or containerized services.
2. Install runtime prerequisites: Python 3.11+, Node.js LTS, Git.
3. Install PostgreSQL via Windows installer; create database, user, and service.
4. Install Redis runtime for Windows (Memurai or WSL-based Redis); enable AOF and RDB.
5. Create a dedicated service account and filesystem layout for logs and data.
6. Populate `.env` with all required keys and verify secrets are not logged.
7. Change API default bind address to 127.0.0.1 and add explicit override via env.
8. Add optional `API_TOKEN` auth to protected API endpoints.
9. Add Prometheus `/metrics` endpoint wired to existing MetricsCollector.
10. Add migration tooling and generate an initial migration from the current schema.
11. Add required indexes for alert and swap queries used by the dashboard API.
12. Fix `block_time` to use actual slot timestamps or a safe fallback.
13. Add TTL to ALT cache entries and validate refresh behavior.
14. Wire wallet clustering output into CTO scoring and document scoring behavior.
15. Persist dedup state across restarts and add recovery tests.
16. Implement P0 unit tests for delta extraction, swap inference, trigger evaluation, and alert formatting.
17. Add integration tests for Discord retry, graceful shutdown, and pending message claiming.
18. Build the frontend for production and serve static assets in the API or a local static server.
19. Add CI workflow to run tests, lint, and frontend build on each push.
20. Align version in pyproject.toml with CHANGELOG.md and add a minimal README.
21. Create a production runbook for start, stop, backup, and restore procedures.
22. Configure Windows services with NSSM for worker and API, including restart policies.
23. Run a 24 hour soak test and record alert loss, backlog, and lag metrics.
24. Manually validate 10 alerts against Solscan and document findings.
25. Finalize release checklist and snapshot the production configuration.

## Error Handling
- Startup fails fast if required environment variables are missing or invalid.
- External API errors use retries and backoff where safe; failures are recorded in metrics.
- Redis or Postgres connection loss triggers degraded mode and alerts; services auto-restart.
- Service restart policy ensures crashes do not leave streams unprocessed.

## Testing Strategy
- Unit tests: parser deltas, swap inference, triggers, alert formatting.
- Integration tests: Discord retry, pending-claim on restart, graceful shutdown flush.
- Accuracy test: compare swaps against known Solscan transactions.
- Soak test: 24 hour run with zero alert loss target and metric review.

## Open Questions
- VPS hardware specs and expected load (tx per second, alert rate).
- Preferred Redis for Windows option if Docker is unavailable.
- Backup frequency and retention period for Postgres and Redis.
- Whether the API will ever need remote access beyond localhost.
