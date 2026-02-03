"""Background task for flushing swap events to database."""

import asyncio
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from storage.swap_queue import SwapEventQueue
    from storage.postgres_client import PostgresClient
    from core.monitoring import MetricsCollector

logger = logging.getLogger(__name__)


class SwapFlusher:
    """
    Background task that periodically flushes swap events from queue to database.

    This allows the main processing loop to continue without blocking on DB writes.
    Events are batched for efficient bulk inserts.
    """

    def __init__(
        self,
        queue: "SwapEventQueue",
        postgres: "PostgresClient",
        metrics: "MetricsCollector" = None,
        flush_interval: float = 1.0,
        batch_size: int = 500,
    ):
        self.queue = queue
        self.postgres = postgres
        self.metrics = metrics
        self.flush_interval = flush_interval
        self.batch_size = batch_size
        self._running = False
        self._total_flushed = 0
        self._flush_count = 0

    async def run(self):
        """Run the background flusher loop."""
        self._running = True
        logger.info(f"Swap flusher started (interval={self.flush_interval}s, batch={self.batch_size})")

        while self._running:
            try:
                await asyncio.sleep(self.flush_interval)
                await self._flush()
            except asyncio.CancelledError:
                logger.info("Swap flusher cancelled, flushing remaining...")
                await self._flush_all()
                break
            except Exception as e:
                logger.error(f"Swap flusher error: {e}")

        logger.info(f"Swap flusher stopped. Total flushed: {self._total_flushed}")

    async def _flush(self):
        """Flush one batch from queue to database."""
        batch = await self.queue.drain(self.batch_size)
        if not batch:
            return

        start = time.time()
        count = await self.postgres.bulk_insert_swap_events(batch)
        elapsed = time.time() - start

        self._total_flushed += count
        self._flush_count += 1

        if self.metrics:
            self.metrics.set_gauge("swap_queue_pending", self.queue.pending)
            self.metrics.inc("swap_flush_total", count)

        if count > 0:
            logger.debug(f"Flushed {count} swaps in {elapsed*1000:.1f}ms (pending: {self.queue.pending})")

    async def _flush_all(self):
        """Flush all remaining events (called on shutdown)."""
        total = 0
        while True:
            batch = await self.queue.drain(self.batch_size)
            if not batch:
                break
            count = await self.postgres.bulk_insert_swap_events(batch)
            total += count

        if total > 0:
            logger.info(f"Flushed {total} remaining swaps on shutdown")
        self._total_flushed += total

    async def stop(self):
        """Stop the flusher gracefully."""
        self._running = False

    def stats(self) -> dict:
        """Get flusher statistics."""
        return {
            "running": self._running,
            "total_flushed": self._total_flushed,
            "flush_count": self._flush_count,
            "queue_pending": self.queue.pending,
            "queue_dropped": self.queue.dropped,
        }
