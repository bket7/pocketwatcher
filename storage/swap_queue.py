"""Async queue for batching swap event writes."""

import asyncio
import logging
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from storage.models import SwapEvent

logger = logging.getLogger(__name__)


class SwapEventQueue:
    """
    Non-blocking queue for swap events.

    Allows the main processing loop to continue without waiting
    for database writes. Events are batched and flushed periodically.
    """

    def __init__(self, max_size: int = 10000):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max_size)
        self._dropped = 0

    async def put(self, swap_event: "SwapEvent") -> bool:
        """
        Non-blocking put. Returns False if queue is full.
        """
        try:
            self._queue.put_nowait(swap_event)
            return True
        except asyncio.QueueFull:
            self._dropped += 1
            if self._dropped % 100 == 1:  # Log every 100 drops
                logger.warning(f"Swap queue full, dropped {self._dropped} events total")
            return False

    async def drain(self, max_items: int = 500) -> List["SwapEvent"]:
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
        """Number of events waiting to be flushed."""
        return self._queue.qsize()

    @property
    def dropped(self) -> int:
        """Number of events dropped due to full queue."""
        return self._dropped

    def stats(self) -> dict:
        """Get queue statistics."""
        return {
            "pending": self.pending,
            "dropped": self._dropped,
        }
