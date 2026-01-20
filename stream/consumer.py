"""Redis Streams consumer for processing transactions."""

import asyncio
import logging
import time
from typing import Callable, List, Optional, Tuple

from storage.redis_client import RedisClient, CONSUMER_GROUP, TX_STREAM

logger = logging.getLogger(__name__)


class StreamConsumer:
    """
    Redis Streams consumer for processing ingested transactions.

    Reads from the transaction stream using consumer groups for
    crash-safe, parallel processing.
    """

    def __init__(
        self,
        redis_client: RedisClient,
        consumer_name: str = "parser-1",
        batch_size: int = 100,
        block_ms: int = 1000,
    ):
        self.redis = redis_client
        self.consumer_name = consumer_name
        self.batch_size = batch_size
        self.block_ms = block_ms

        self._running = False
        self._processed_count = 0
        self._error_count = 0
        self._start_time = 0

    async def start(
        self,
        on_message: Callable,
        on_error: Optional[Callable] = None,
    ):
        """
        Start consuming messages from the stream.

        Args:
            on_message: Async callback receiving (message_id, raw_data)
            on_error: Optional callback for errors
        """
        self._running = True
        self._start_time = time.time()

        logger.info(f"Consumer {self.consumer_name} starting...")

        while self._running:
            try:
                # Read batch of messages
                messages = await self.redis.read_from_stream(
                    self.consumer_name,
                    count=self.batch_size,
                    block_ms=self.block_ms,
                )

                if not messages:
                    continue

                # Process messages
                ack_ids = []

                for stream_name, stream_messages in messages:
                    for msg_id, fields in stream_messages:
                        try:
                            raw_data = fields.get(b"data") or fields.get("data")
                            if raw_data:
                                await on_message(msg_id, raw_data)
                                self._processed_count += 1
                            ack_ids.append(msg_id)
                        except Exception as e:
                            self._error_count += 1
                            logger.error(f"Error processing message {msg_id}: {e}")
                            if on_error:
                                await on_error(msg_id, e)
                            # Still ack to avoid infinite retry
                            ack_ids.append(msg_id)

                # Acknowledge processed messages
                if ack_ids:
                    await self.redis.ack_messages(ack_ids)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Consumer error: {e}")
                if on_error:
                    await on_error(None, e)
                await asyncio.sleep(1)  # Brief pause on error

        logger.info(f"Consumer {self.consumer_name} stopped")

    def stop(self):
        """Signal to stop consuming."""
        self._running = False

    def get_stats(self) -> dict:
        """Get consumer statistics."""
        uptime = time.time() - self._start_time if self._start_time > 0 else 0
        msgs_per_sec = self._processed_count / uptime if uptime > 0 else 0

        return {
            "consumer_name": self.consumer_name,
            "processed_count": self._processed_count,
            "error_count": self._error_count,
            "uptime_seconds": uptime,
            "messages_per_second": msgs_per_sec,
            "running": self._running,
        }


class MultiConsumer:
    """
    Multi-consumer manager for parallel stream processing.

    Spawns multiple consumers in the same consumer group for
    increased throughput.
    """

    def __init__(
        self,
        redis_client: RedisClient,
        num_consumers: int = 2,
        batch_size: int = 100,
        block_ms: int = 1000,
    ):
        self.redis = redis_client
        self.num_consumers = num_consumers
        self.batch_size = batch_size
        self.block_ms = block_ms

        self._consumers: List[StreamConsumer] = []
        self._tasks: List[asyncio.Task] = []

    async def start(
        self,
        on_message: Callable,
        on_error: Optional[Callable] = None,
    ):
        """Start all consumers."""
        for i in range(self.num_consumers):
            consumer = StreamConsumer(
                self.redis,
                consumer_name=f"parser-{i+1}",
                batch_size=self.batch_size,
                block_ms=self.block_ms,
            )
            self._consumers.append(consumer)

            task = asyncio.create_task(
                consumer.start(on_message, on_error)
            )
            self._tasks.append(task)

        logger.info(f"Started {self.num_consumers} consumers")

    async def stop(self):
        """Stop all consumers."""
        for consumer in self._consumers:
            consumer.stop()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        self._consumers = []
        self._tasks = []

        logger.info("All consumers stopped")

    def get_stats(self) -> dict:
        """Get aggregate statistics from all consumers."""
        total_processed = sum(c._processed_count for c in self._consumers)
        total_errors = sum(c._error_count for c in self._consumers)

        return {
            "num_consumers": len(self._consumers),
            "total_processed": total_processed,
            "total_errors": total_errors,
            "consumers": [c.get_stats() for c in self._consumers],
        }
