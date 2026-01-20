# Pocketwatcher: Validation Guide & Tech Debt

## How to Know It's Working

### Quick Health Checks

```bash
# 1. Check stats are incrementing (swaps should increase over time)
grep "Stats:" <log_output> | tail -5

# 2. Check Discord alerts are being sent
grep "Discord alert sent" <log_output> | wc -l

# 3. Check stream isn't backing up
grep "stream=" <log_output> | tail -1
# Should show stream=<number under 50k for NORMAL mode>

# 4. Check both consumers are running
grep "Consumer parser" <log_output>
# Should see parser-1 and parser-2 starting
```

### Key Metrics to Monitor

| Metric | Healthy | Warning | Critical |
|--------|---------|---------|----------|
| tx/s | 50-200+ | 10-50 | <10 |
| swaps | Increasing | Flat | 0 |
| stream backlog | <50k | 50k-80k | >80k |
| lag | <5s | 5-30s | >30s |
| HOT tokens | Growing then stable | - | - |

---

## Validating Data Accuracy

### Manual Spot Checks (Do These First!)

1. **Pick 3 Discord alerts** → Open Solscan for the mint address
2. **Verify the trigger makes sense:**
   - `extreme_ratio` → Should see mostly buys, few/no sells
   - `whale_concentration` → Top wallets should own most volume
3. **Check CTO score aligns with wallet patterns**

### Automated Validation Tests to Write

```python
# tests/test_swap_accuracy.py

async def test_swap_detection_against_solscan():
    """Compare our detected swaps against Solscan for a known tx."""
    # Use a known pump.fun swap transaction
    known_tx = "5abc..."  # Get from Solscan

    # Parse with our system
    result = await processor.process_transaction(tx_data)

    # Verify against known values
    assert result.swap.side == "buy"
    assert result.swap.base_mint == "expected_mint"
    assert abs(result.swap.quote_amount - expected_sol) < 0.01

async def test_delta_extraction_accuracy():
    """Verify balance deltas match pre/post differences."""
    # Test with known transaction data
    token_deltas, sol_deltas = delta_builder.build_deltas(tx_data)

    # Manually calculated expected values
    assert token_deltas[("owner", "mint")] == expected_delta

async def test_trigger_thresholds():
    """Verify triggers fire at correct thresholds."""
    # Create mock stats at threshold boundaries
    stats_below = TokenStats(buy_sell_ratio=9.9)  # Below 10
    stats_at = TokenStats(buy_sell_ratio=10.1)    # Above 10

    assert not evaluator.evaluate(stats_below).triggered
    assert evaluator.evaluate(stats_at).triggered
```

### Accuracy Benchmarks (MVP Targets)

| Metric | Target | How to Measure |
|--------|--------|----------------|
| Swap detection rate | 70-90% | `swaps / total_txs_with_token_deltas` |
| Swap side accuracy | 95%+ | Manual spot check 20 swaps vs Solscan |
| Trigger precision | 80%+ | Of alerts sent, how many are real accumulation |
| False positive rate | <20% | Alerts for tokens that aren't actually suspicious |

---

## Tests to Write (Priority Order)

### P0: Critical Path Tests

```
tests/
├── test_delta_extraction.py    # Balance delta math is correct
├── test_swap_inference.py      # Buy/sell detection works
├── test_trigger_evaluation.py  # Thresholds fire correctly
└── test_alert_formatting.py    # Discord embeds render properly
```

### P1: Integration Tests

```
tests/
├── test_yellowstone_parsing.py # Protobuf → dict conversion
├── test_redis_counters.py      # Rolling windows calculate correctly
├── test_backpressure.py        # Mode transitions work
└── test_consumer_scaling.py    # Multi-consumer doesn't duplicate
```

### P2: End-to-End Tests

```
tests/
├── test_full_pipeline.py       # Mock tx → alert sent
├── test_cto_scoring.py         # Cluster detection accuracy
└── test_enrichment_budget.py   # Helius credits stay in limit
```

### Sample Test Fixtures Needed

```python
# tests/fixtures/transactions.py

PUMP_FUN_BUY_TX = {
    "signature": "...",
    "pre_token_balances": [...],
    "post_token_balances": [...],
    # ... real pump.fun buy transaction
}

JUPITER_MULTI_HOP_TX = {
    # Jupiter swap through multiple pools
}

RAYDIUM_SELL_TX = {
    # Raydium AMM sell
}
```

---

## Tech Debt to Annihilate

### Critical (Fix Now)

| Issue | File | Impact | Fix |
|-------|------|--------|-----|
| No tests exist | - | Can't verify correctness | Write P0 tests |
| Hardcoded confidence penalties | inference.py | Can't tune accuracy | Move to config |
| No swap validation logging | processor.py | Can't debug misses | Add debug mode |

### High Priority (This Week)

| Issue | File | Impact | Fix |
|-------|------|--------|-----|
| `block_time=0` always | main.py:292 | Can't calculate real lag | Extract from proto or estimate |
| Health check caches old values | monitoring.py | Stale warnings | Already fixed in v0.1.2 |
| No retry on Discord failure | discord.py | Lost alerts | Add retry with backoff |
| CTO score always 25% or 55% | scoring.py | Not using real cluster data | Wire up actual clustering |

### Medium Priority (This Month)

| Issue | File | Impact | Fix |
|-------|------|--------|-----|
| ALT cache never invalidated | alt_cache.py | Stale lookups | Add TTL or LRU |
| No graceful shutdown | main.py | Data loss on kill | Handle SIGTERM properly |
| Wallet clustering untested | clustering.py | Unknown accuracy | Add tests + validation |
| No dedup across restarts | dedup.py | Reprocessing on restart | Persist last processed |
| WSOL normalization edge cases | deltas.py | Missed swaps | Test with real data |

### Low Priority (Backlog)

| Issue | File | Impact | Fix |
|-------|------|--------|-----|
| No Telegram support | telegram.py | Missing alert channel | Implement if needed |
| Postgres queries not optimized | postgres_client.py | Slow at scale | Add indexes, batch writes |
| No metrics export (Prometheus) | monitoring.py | Can't graph trends | Add /metrics endpoint |
| Config hot-reload incomplete | redis_client.py | Requires restart | Finish pubsub listener |

---

## Recommended Next Steps

### Today
1. Let it run for 30 min, collect 10+ alerts
2. Manually verify 5 alerts against Solscan
3. Note any obvious false positives/negatives

### This Week
1. Write `test_delta_extraction.py` with 5 real transactions
2. Write `test_swap_inference.py` with buy/sell cases
3. Fix `block_time=0` to get real lag metrics
4. Add retry logic to Discord alerter

### This Month
1. Full P0 + P1 test coverage
2. CTO scoring connected to real clustering
3. Accuracy benchmark: target 80%+ precision
4. Backpressure tuning based on real load patterns

---

## Quick Validation Commands

```bash
# Count alerts by trigger type
grep "became HOT" log.txt | grep -o "Trigger: [^|]*" | sort | uniq -c

# Check swap detection rate
TOTAL=$(grep "tx_processed_total" log.txt | tail -1)
SWAPS=$(grep "swaps_detected" log.txt | tail -1)
echo "Detection rate: $SWAPS / $TOTAL"

# Find potential false positives (HOT tokens with low activity)
grep "became HOT" log.txt | grep "buy_sell_ratio_5m=inf"
# These might be single-buy tokens, not real accumulation

# Verify no duplicate processing
grep "Alert sent" log.txt | awk '{print $NF}' | sort | uniq -c | sort -rn | head
# Each mint should appear once (or few times if re-triggered)
```
