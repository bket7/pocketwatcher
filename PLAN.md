# Pocketwatcher - Production Readiness Plan

## Current Status: 95% Production Ready

**Version:** 0.2.5
**Last Updated:** 2026-02-03

## What's Done ✅

- [x] Core pipeline (streaming → parsing → detection → alerting)
- [x] Web dashboard with config hot-reload
- [x] 28 unit tests passing
- [x] Backtest dashboard for performance tracking
- [x] Trigger tuning based on backtest data
- [x] Market cap filter (skip <500 SOL mcap)
- [x] Discord + Telegram alerting
- [x] Redis Streams with consumer groups (crash-safe)
- [x] PostgreSQL persistence for alerts/swaps

---

## Production Blockers 🚨

### 1. Discord Retry with Exponential Backoff
**File:** `alerting/discord.py`
**Issue:** Only retries on 429 (rate limit). Network errors and 5xx responses cause lost alerts.

**Fix:**
```python
# Add retry logic in send_alert():
MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]  # exponential backoff

for attempt in range(MAX_RETRIES):
    try:
        response = await self._http_client.post(...)
        if response.status_code >= 500:
            raise httpx.HTTPStatusError("Server error", request=..., response=response)
        response.raise_for_status()
        return True
    except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e:
        if attempt < MAX_RETRIES - 1:
            await asyncio.sleep(RETRY_DELAYS[attempt])
            continue
        logger.error(f"Discord send failed after {MAX_RETRIES} attempts: {e}")
        return False
```

**Acceptance:** Alert delivery survives transient network issues.

---

### 2. Graceful Shutdown (Windows Compatible)
**File:** `main.py`
**Issue:** `add_signal_handler` doesn't work on Windows. SIGTERM not caught.

**Fix:**
```python
# Replace signal handler setup with cross-platform version:
import signal

def setup_signal_handlers(app):
    def handler(signum, frame):
        logger.info(f"Received signal {signum}")
        asyncio.create_task(app.stop())

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
    # Windows also supports SIGBREAK
    if hasattr(signal, 'SIGBREAK'):
        signal.signal(signal.SIGBREAK, handler)
```

**Acceptance:** `taskkill /PID xxx` triggers clean shutdown with log flush.

---

### 3. Claim Pending Messages on Restart
**File:** `stream/consumer.py`
**Issue:** On restart, pending (unACKed) messages from previous run aren't re-processed.

**Fix:**
```python
# Add to StreamConsumer.start() before main loop:
async def _claim_pending(self):
    """Claim and process any pending messages from previous runs."""
    pending = await self.redis.redis.xpending_range(
        TX_STREAM, CONSUMER_GROUP,
        min="-", max="+", count=1000,
        consumername=self.consumer_name
    )
    if pending:
        logger.info(f"Claiming {len(pending)} pending messages")
        ids = [p['message_id'] for p in pending]
        # Claim messages idle > 30s
        claimed = await self.redis.redis.xclaim(
            TX_STREAM, CONSUMER_GROUP, self.consumer_name,
            min_idle_time=30000, message_ids=ids
        )
        return claimed
    return []
```

**Acceptance:** Messages survive app crash without loss.

---

## High Priority (Post-Launch) 📋

### 4. Fix block_time=0
**File:** `main.py:314`
**Issue:** `block_time: 0` in tx dict means lag calculation is wrong.

**Fix:** Extract from slot using known slot→timestamp mapping, or estimate from current time.

---

### 5. ALT Cache TTL
**File:** `parser/alt_cache.py`
**Issue:** Address Lookup Table cache never expires, could serve stale data.

**Fix:** Add 1-hour TTL to cached lookups.

---

### 6. CTO Score Using Real Clusters
**File:** `enrichment/scoring.py`
**Issue:** Always returns 25% or 55%, not using actual wallet clustering.

**Fix:** Wire `WalletClusterer` output into `CTOScorer.score()`.

---

## Test Coverage Gaps 🧪

Priority tests to add (from VALIDATION_AND_DEBT.md):

| Test | Purpose |
|------|---------|
| `test_discord_retry.py` | Verify retry + backoff works |
| `test_graceful_shutdown.py` | Verify clean stop flushes data |
| `test_pending_claim.py` | Verify pending messages processed |
| `test_swap_accuracy.py` | Compare vs Solscan ground truth |

---

## Pre-Launch Checklist

- [x] Implement Discord retry with backoff
- [x] Implement Windows-compatible signal handlers
- [x] Implement pending message claiming on restart
- [ ] Run for 24h with no lost alerts
- [ ] Manual spot-check 10 alerts against Solscan
- [x] Commit + push all changes

---

## Commands

```bash
# Run tests
python -m pytest tests/ -v

# Start with debug logging
python main.py --debug

# Check alert gaps
python scripts/investigate_alerts.py
```

---

## Notes

_Working through production blockers in order. ETA: ready after items 1-3 complete._
