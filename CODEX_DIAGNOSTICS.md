# Pocketwatcher Diagnostic Issues for Codex

## Current Status
- System connects to Yellowstone and streams transactions successfully
- Discord alerts are being sent for HOT tokens
- Detection triggers (extreme_ratio, whale_concentration) are firing
- **BUT: "0 swaps" in stats despite triggers firing**

## Issues to Investigate and Fix

### Issue 1: Swap Detection Shows 0 Despite Triggers Firing
**Symptoms:**
- Stats log shows `0 swaps` even when in NORMAL mode
- Detection triggers ARE firing with values like `buy_sell_ratio_5m=inf`
- This means counters ARE being updated somewhere, but `_swap_count` isn't incrementing

**Files to investigate:**
- `core/processor.py` lines 157-176 (swap inference branch)
- `parser/inference.py` (swap detection logic)
- `parser/deltas.py` (balance delta extraction)

**Key questions:**
1. Is `infer_swap()` returning None for most transactions?
2. Is the confidence score below 0.7 threshold?
3. Are token balances being parsed correctly from Yellowstone protobuf?

**Debug approach:**
- Add logging in `process_transaction()` to log:
  - How many transactions have non-empty `token_deltas`
  - How many times `infer_swap()` returns a non-None result
  - What confidence scores are being calculated
- Check if `pre_token_balances` and `post_token_balances` are being populated correctly in `_tx_to_dict()`

### Issue 2: Counters Being Updated Without Swap Detection
**Symptoms:**
- Triggers fire with `buy_sell_ratio_5m=inf` (buy_count > 0, sell_count = 0)
- This means `record_swap()` IS being called somewhere
- But the metrics `swaps_detected` counter stays at 0

**Files to investigate:**
- `detection/counters.py` - `record_swap()` method
- `core/processor.py` - all calls to `counter_manager.record_swap()`
- Search for any other code path that might update counters

**Key questions:**
1. Is there a code path that updates counters without going through the swap detection metrics?
2. Are the metrics being reset somewhere?

### Issue 3: Backpressure Recovers But Stream Fills Up Fast
**Symptoms:**
- System enters CRITICAL mode immediately on startup due to existing backlog
- After clearing stream, recovers to NORMAL
- But backlog builds up again over time

**Files to investigate:**
- `core/backpressure.py` - degradation thresholds
- `stream/consumer.py` - consumption rate
- `stream/yellowstone.py` - ingest rate

**Potential improvements:**
- Increase consumer parallelism
- Adjust backpressure thresholds
- Add faster DEGRADED mode processing that still counts swaps

### Issue 4: Health Check Shows Stale Data
**Symptoms:**
- `Health issues: ['Large stream backlog: 100000']` still shows after stream was cleared
- Backpressure correctly shows `stream=218` but health check shows old value

**Files to investigate:**
- `core/monitoring.py` - health check implementation
- Check if stream length is being cached

## How to Add Debug Logging

Add this to `core/processor.py` around line 160:

```python
# Debug swap detection
if token_deltas:
    logger.debug(f"TX {signature[:8]} has {len(token_deltas)} token deltas")
    swap = self.inference.infer_swap(token_deltas, sol_deltas, candidates)
    if swap:
        logger.debug(f"TX {signature[:8]} swap detected: {swap.side} confidence={swap.confidence}")
    else:
        logger.debug(f"TX {signature[:8]} no swap inferred")
```

## Test Commands

```bash
# Clear Redis stream backlog
python -c "import redis; r = redis.Redis(); print(r.xtrim('stream:tx', maxlen=0))"

# Check Redis stream length
python -c "import redis; r = redis.Redis(); print(r.xlen('stream:tx'))"

# Check swap inference stats
# Add this endpoint or log the inference.get_stats() results
```

## Expected Fix Outcomes

1. Stats should show `X swaps` when in NORMAL mode (not 0)
2. Swap detection rate should be 70-90% as per spec
3. If confidence is consistently low, adjust the confidence calculation
4. If token deltas are empty, fix the protobuf parsing in `_tx_to_dict()`
