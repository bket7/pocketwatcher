# Pocketwatcher Performance Improvement Plan

**Created**: 2026-02-05
**Goal**: Increase throughput from ~320-370 tx/s to 400-600 tx/s

---

## Phase 1: Fix Correctness Bugs (BLOCKING)

These must be fixed before any performance work. Scaling with bugs makes debugging impossible.

### 1.1 Bug A: Pending claim drops work silently
**File**: `stream/batch_consumer.py:273-328` (`_claim_pending_messages()`)

**Problem**: Claimed pending messages are ACKed without being processed (line 319-321 has `pass` where processing should happen).

**Impact**: Any message not ACKed on first attempt is silently lost when reclaimed.

**Fix**:
- Process claimed messages through the same batch pipeline as new messages
- Pass claimed `raw_messages` to the batch handler (`on_batch`)
- Only ACK after successful processing
- Alternatively, re-inject messages back into the stream for normal processing

### 1.2 Bug B: Pipeline write depends on loop variable
**File**: `stream/batch_consumer.py:467` (`BatchContext._execute_writes()`)

**Problem**: `wallet:first_seen:{wallet}` is written OUTSIDE the counter update loop:
```python
for update in self._counter_updates.values():
    wallet = update["user_wallet"]
    # ... loop body
pipe.set(f"wallet:first_seen:{wallet}", now, nx=True, ex=86400 * 7)  # OUTSIDE LOOP!
```

**Impact**:
1. If `_counter_updates` is empty, `wallet` is undefined → exception → ACK never executes → XPENDING rises
2. Only writes `first_seen` for the last wallet, not all wallets

**Fix**:
- Move the `first_seen` write INSIDE the loop
- Wrap non-critical writes in try/except so ACK always executes
- Never let a cosmetic write failure prevent acknowledgment

---

## Phase 2: Profile Before Optimizing

### 2.1 Quick Diagnostics (no code changes)

1. **Check CPU usage** of python worker:
   - If pegging ~1 core (12-25% on 8-core) → GIL/CPU-bound → multi-process mandatory
   - If CPU low → bottleneck is I/O (Redis RTT) → different fix

2. **Check detection loop CPU theft**:
   - Temporarily disable detection loop, observe tx/s
   - If tx/s jumps → detection must run in separate process

3. **Watch XPENDING during error bursts**:
   - Correlate XPENDING spikes with log errors → confirms Bug B fix worked

### 2.2 Profiling with py-spy

```powershell
pip install py-spy
py-spy record --gil --pid <WORKER_PID> -o profile.svg -d 30
```

Analyze flame graph for:
- Where CPU time is spent
- GIL contention patterns
- Hot functions (parsing? inference? serialization?)

---

## Phase 3: Quick Wins (10-30% each)

### 3.1 Install hiredis
```powershell
pip install hiredis
```
- No code changes needed
- redis-py auto-detects and uses C-based RESP parsing

### 3.2 Verify orjson/msgpack usage
- Codebase uses `msgpack` (good) - verify no `json.loads/dumps` in hot path
- If found, replace with `orjson`

### 3.3 Verify Redis pipeline batching
- Confirm ACKs and counter updates are truly batched (not sequential in same pipeline call)
- Current code looks correct but verify empirically

### 3.4 Tune XREADGROUP parameters
- Recommended: `COUNT=100-512`, `BLOCK=500-2000`
- Current: `batch_size=512`, `block_ms=500` (looks good)

---

## Phase 4: Multi-Process Split (The Big Fix)

### 4.1 Target Architecture

```
Process A: INGEST ONLY
  Yellowstone gRPC → Redis stream (XADD)
  No parsing, no Postgres, no detection

Process B/C/D: CONSUME ONLY (2-4 instances)
  Redis stream → BatchConsumer → BatchProcessor
  Parsing, inference, counters, DB queue
  Each process: 2-4 async consumers

Process E: DETECTION/ALERTS ONLY (exactly 1)
  Reads counters from Redis
  Emits Discord/Telegram alerts
  Single instance to avoid duplicate alerts
```

### 4.2 Implementation: CLI Flags

Add to `main.py`:
- `--ingest-only` → runs only Yellowstone → Redis
- `--consume-only` → runs only BatchConsumer workers
- `--detect-only` → runs only detection/alerts
- No flags → current behavior (backward compatible)

### 4.3 Consumer Naming

Use `CONSUMER_NAME` env var or derive from `hostname-pid`:
```
parser-{hostname}-{pid}
```

### 4.4 NSSM Service Setup

```
pocketwatcher-ingest   → python main.py --ingest-only
pocketwatcher-worker-1 → python main.py --consume-only
pocketwatcher-worker-2 → python main.py --consume-only
pocketwatcher-worker-3 → python main.py --consume-only
pocketwatcher-detect   → python main.py --detect-only
```

### 4.5 Pending Recovery

Use `XAUTOCLAIM` (Redis 6.2+):
```
XAUTOCLAIM stream:tx parsers recovery-worker 60000 0-0 COUNT 100
```
Run dedicated recovery sweep every 30-60 seconds.

---

## Phase 5: Advanced (Only If Still Short)

- **5a**: Cython for hot-path functions
- **5b**: Rust/PyO3 for Solana tx parsing
- **5c**: Python 3.14 free-threaded mode (experimental)
- **5d**: PyPy (hiredis compatibility issues)

---

## Execution Order

| Step | Task | Est. Risk | Files |
|------|------|-----------|-------|
| 1 | Fix Bug A (pending claim) | Low | `stream/batch_consumer.py` |
| 2 | Fix Bug B (first_seen loop) | Low | `stream/batch_consumer.py` |
| 3 | Verify fixes via XPENDING monitoring | None | - |
| 4 | Profile with py-spy | None | - |
| 5 | Install hiredis | Low | requirements.txt |
| 6 | Verify msgpack usage (no json) | Low | - |
| 7 | Add CLI flags for multi-process | Medium | `main.py` |
| 8 | Test single-process with flags | Low | - |
| 9 | Deploy 2-4 consume processes | Medium | NSSM config |
| 10 | Monitor tx/s and XPENDING | None | - |

---

## Verification Commands

```powershell
# Stream backlog
python -c "import redis; r=redis.Redis.from_url('redis://localhost:6379/0', decode_responses=True); print('XLEN:', r.xlen('stream:tx'))"

# Pending messages
python -c "import redis; r=redis.Redis.from_url('redis://localhost:6379/0', decode_responses=True); print(r.xpending('stream:tx','parsers'))"

# Live stats
python -c "import redis, json; r=redis.Redis.from_url('redis://localhost:6379/0', decode_responses=True); print(json.dumps(json.loads(r.get('pocketwatcher:live_stats')), indent=2))"

# CPU usage
tasklist | findstr python
```

---

## Success Criteria

- [ ] XPENDING stabilizes at low values (< 1000)
- [ ] Stream length drains (XLEN decreases when ingest pauses)
- [ ] tx/s reaches 400-600 range
- [ ] No silent data loss from claimed pending messages
