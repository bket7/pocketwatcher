# Background DB Writes - Implementation Plan

Version: a
Date: 2026-02-03

## Problem
Processing ~225 tx/s but receiving ~400+ tx/s. Main bottleneck is synchronous PostgreSQL writes blocking the processing loop.

## Solution
Move swap_event inserts to a background queue. Batch writes every 1-2 seconds instead of per-transaction.

## Architecture

```
Current:
  tx → parse → insert_swap_event (BLOCKS) → update_counters → check_triggers
                     ↓
               ~5-10ms wait

Proposed:
  tx → parse → queue.put(swap_event) → update_counters → check_triggers
                     ↓
               ~0.01ms (non-blocking)

  Background flusher (separate task):
    every 1s: batch = queue.drain() → bulk_insert(batch)
```

## Implementation Steps

### Step 1: Create SwapEventQueue class
Location: `storage/swap_queue.py`

```python
class SwapEventQueue:
    def __init__(self, max_size=10000):
        self._queue = asyncio.Queue(maxsize=max_size)
        self._pending_count = 0

    async def put(self, swap_event: SwapEvent):
        """Non-blocking put. Drops if full."""
        try:
            self._queue.put_nowait(swap_event)
            self._pending_count += 1
        except asyncio.QueueFull:
            logger.warning("Swap queue full, dropping event")

    async def drain(self, max_items=500) -> List[SwapEvent]:
        """Drain up to max_items from queue."""
        items = []
        while len(items) < max_items:
            try:
                item = self._queue.get_nowait()
                items.append(item)
            except asyncio.QueueEmpty:
                break
        return items

    @property
    def pending(self) -> int:
        return self._queue.qsize()
```

### Step 2: Add bulk insert to PostgresClient
Location: `storage/postgres_client.py`

```python
async def bulk_insert_swap_events(self, events: List[SwapEvent]) -> int:
    """Insert multiple swap events in single transaction."""
    if not events:
        return 0

    async with self.pool.acquire() as conn:
        # Use COPY or executemany for efficiency
        await conn.executemany(
            """
            INSERT INTO swap_events (signature, slot, block_time, venue, ...)
            VALUES ($1, $2, $3, $4, ...)
            ON CONFLICT (signature, base_mint) DO NOTHING
            """,
            [(e.signature, e.slot, e.block_time, e.venue, ...) for e in events]
        )
    return len(events)
```

### Step 3: Create background flusher task
Location: `core/processor.py` or new `core/swap_flusher.py`

```python
class SwapFlusher:
    def __init__(self, queue: SwapEventQueue, postgres: PostgresClient):
        self.queue = queue
        self.postgres = postgres
        self._running = False
        self._flush_interval = 1.0  # seconds
        self._batch_size = 500

    async def run(self):
        """Background task to flush swap events to DB."""
        self._running = True
        while self._running:
            try:
                await asyncio.sleep(self._flush_interval)
                batch = await self.queue.drain(self._batch_size)
                if batch:
                    count = await self.postgres.bulk_insert_swap_events(batch)
                    logger.debug(f"Flushed {count} swap events to DB")
            except asyncio.CancelledError:
                # Flush remaining on shutdown
                batch = await self.queue.drain(10000)
                if batch:
                    await self.postgres.bulk_insert_swap_events(batch)
                break
            except Exception as e:
                logger.error(f"Swap flusher error: {e}")

    async def stop(self):
        self._running = False
```

### Step 4: Modify TransactionProcessor
Location: `core/processor.py`

Change from:
```python
await self.postgres.insert_swap_event(swap_event)
```

To:
```python
await self.swap_queue.put(swap_event)
```

### Step 5: Wire up in Application
Location: `main.py`

```python
# In Application.__init__
self.swap_queue = SwapEventQueue(max_size=10000)
self.swap_flusher = SwapFlusher(self.swap_queue, self.postgres)

# In Application.run
tasks = [
    ...existing tasks...,
    asyncio.create_task(self.swap_flusher.run()),
]

# In Application.stop
await self.swap_flusher.stop()
```

### Step 6: Add metrics
- `swap_queue_size` gauge - monitor queue depth
- `swap_flush_count` counter - track flushes
- `swap_flush_duration` histogram - track flush latency

## Testing
1. Unit test: SwapEventQueue put/drain behavior
2. Unit test: bulk_insert_swap_events with duplicates
3. Integration test: graceful shutdown flushes pending
4. Load test: verify throughput improvement

## Rollback
If issues arise, revert to synchronous writes by changing:
```python
await self.swap_queue.put(swap_event)
```
back to:
```python
await self.postgres.insert_swap_event(swap_event)
```

## Expected Impact
- Processing speed: 225 tx/s → 400-500 tx/s
- Swap data latency: 0ms → 1-2s (acceptable for historical data)
- Memory: +5-10MB for queue buffer
- Alert latency: unchanged (alerts don't depend on swap_events table)

## Files Modified
1. `storage/swap_queue.py` (new)
2. `storage/postgres_client.py` (add bulk_insert)
3. `core/processor.py` (use queue instead of direct insert)
4. `main.py` (wire up flusher task)
5. `core/monitoring.py` (add queue metrics)
