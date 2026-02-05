"""
Pocketwatcher: Solana CTO/Stealth-Accumulation Monitor

Main entry point for the application.
"""

import asyncio
import json
import logging
import signal
import sys
import time
from typing import Optional, Union

from config.settings import settings
from storage.redis_client import RedisClient
from storage.postgres_client import PostgresClient
from storage.delta_log import DeltaLog
from storage.event_log import EventLog
from stream.yellowstone import YellowstoneClient, MockYellowstoneClient
from stream.consumer import StreamConsumer, MultiConsumer
from stream.batch_consumer import BatchConsumer, MultiBatchConsumer
from stream.dedup import DedupFilter
from core.batch_processor import BatchProcessor
from parser.alt_cache import ALTCache
from enrichment.helius import HeliusClient
from alerting.discord import DiscordAlerter
from alerting.telegram import TelegramAlerter
from core.processor import TransactionProcessor
from core.monitoring import MetricsCollector, HealthChecker
from core.swap_flusher import SwapFlusher
from storage.swap_queue import SwapEventQueue

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)

logger = logging.getLogger("pocketwatcher")


class Application:
    """Main application class orchestrating all components."""

    def __init__(
        self,
        use_mock_stream: bool = False,
        high_throughput: bool = True,
        mode: str = "all",
        consumer_name: Optional[str] = None,
    ):
        self.use_mock_stream = use_mock_stream
        self.high_throughput = high_throughput  # Use batched consumer with Redis pipelining
        self.mode = mode  # "all", "ingest", "consume", or "detect"
        self.consumer_name = consumer_name
        self._running = False
        self._shutdown_event = asyncio.Event()

        # Components (initialized in start())
        self.redis: Optional[RedisClient] = None
        self.postgres: Optional[PostgresClient] = None
        self.delta_log: Optional[DeltaLog] = None
        self.event_log: Optional[EventLog] = None
        self.yellowstone: Optional[YellowstoneClient] = None
        self.consumer: Optional[Union[StreamConsumer, MultiConsumer, MultiBatchConsumer]] = None
        self.batch_consumer: Optional[MultiBatchConsumer] = None
        self.dedup: Optional[DedupFilter] = None
        self.alt_cache: Optional[ALTCache] = None
        self.helius: Optional[HeliusClient] = None
        self.discord: Optional[DiscordAlerter] = None
        self.telegram: Optional[TelegramAlerter] = None
        self.processor: Optional[TransactionProcessor] = None
        self.batch_processor: Optional[BatchProcessor] = None
        self.metrics: Optional[MetricsCollector] = None
        self.health_checker: Optional[HealthChecker] = None
        self.swap_queue: Optional[SwapEventQueue] = None
        self.swap_flusher: Optional[SwapFlusher] = None

        # Tasks
        self._tasks = []

    async def start(self):
        """Start components based on run mode."""
        mode_desc = {
            "all": "full mode",
            "ingest": "INGEST-ONLY mode",
            "consume": "CONSUME-ONLY mode",
            "detect": "DETECT-ONLY mode",
        }
        logger.info(f"Starting Pocketwatcher in {mode_desc.get(self.mode, self.mode)}...")

        # Initialize metrics (always needed)
        self.metrics = MetricsCollector()

        # Initialize Redis (always needed)
        logger.info("Connecting to Redis...")
        self.redis = RedisClient()
        await self.redis.connect()

        # Components needed for ingest mode
        needs_ingest = self.mode in ("all", "ingest")
        # Components needed for consume mode
        needs_consume = self.mode in ("all", "consume")
        # Components needed for detect mode
        needs_detect = self.mode in ("all", "detect")

        # PostgreSQL (needed for consume and detect)
        if needs_consume or needs_detect:
            logger.info("Connecting to PostgreSQL...")
            self.postgres = PostgresClient()
            await self.postgres.connect()

        # Delta/Event logs (needed for consume)
        if needs_consume:
            logger.info("Initializing logs...")
            self.delta_log = DeltaLog()
            await self.delta_log.start()
            self.event_log = EventLog()
            await self.event_log.start()

        # Yellowstone client (needed for ingest)
        if needs_ingest:
            logger.info("Initializing stream client...")
            if self.use_mock_stream:
                self.yellowstone = MockYellowstoneClient()
            else:
                self.yellowstone = YellowstoneClient()
            await self.yellowstone.load_programs()

        # Dedup filter (needed for legacy consume mode)
        if needs_consume:
            self.dedup = DedupFilter(self.redis)

        # ALT cache (needed for consume)
        if needs_consume:
            self.alt_cache = ALTCache()
            await self.alt_cache.start()

        # Helius client (needed for detect - enrichment during alerts)
        if needs_detect:
            logger.info("Initializing Helius client...")
            self.helius = HeliusClient()
            await self.helius.start()

        # Alerters (needed for detect)
        if needs_detect:
            logger.info("Initializing alerters...")
            self.discord = DiscordAlerter()
            await self.discord.start()
            self.telegram = TelegramAlerter()
            await self.telegram.start()

        # Swap queue and flusher (needed for consume)
        if needs_consume:
            logger.info("Initializing swap queue...")
            self.swap_queue = SwapEventQueue(max_size=10000)
            self.swap_flusher = SwapFlusher(
                queue=self.swap_queue,
                postgres=self.postgres,
                metrics=self.metrics,
                flush_interval=1.0,
                batch_size=500,
            )

        # Transaction processor (needed for detect, and consume in legacy mode)
        # Also needed for consume to share counter_manager
        if needs_detect or needs_consume:
            logger.info("Initializing transaction processor...")
            # For consume-only, we may not have yellowstone, so pass empty set
            known_programs = getattr(self.yellowstone, 'known_programs', set()) if self.yellowstone else set()
            self.processor = TransactionProcessor(
                redis_client=self.redis,
                postgres_client=self.postgres,
                delta_log=self.delta_log,
                event_log=self.event_log,
                helius_client=self.helius,
                discord_alerter=self.discord,
                telegram_alerter=self.telegram,
                metrics=self.metrics,
                known_programs=known_programs,
                swap_queue=self.swap_queue,
            )
            await self.processor.initialize()

            # Config hot-reload (needed for detect)
            if needs_detect:
                await self.processor.trigger_evaluator.start_config_listener()

        # Consumer initialization (needed for consume)
        if needs_consume:
            consumer_count = max(1, settings.stream_consumer_count)
            known_programs = getattr(self.yellowstone, 'known_programs', set()) if self.yellowstone else set()

            if self.high_throughput:
                logger.info("Using HIGH-THROUGHPUT mode with Redis pipelining")
                self.batch_processor = BatchProcessor(
                    delta_log=self.delta_log,
                    event_log=self.event_log,
                    swap_queue=self.swap_queue,
                    metrics=self.metrics,
                    known_programs=known_programs,
                    counter_manager=self.processor.counter_manager if self.processor else None,
                )
                self.batch_consumer = MultiBatchConsumer(
                    self.redis,
                    num_consumers=min(consumer_count, 8),
                    batch_size=512,
                    block_ms=500,
                )
            else:
                if consumer_count > 1:
                    self.consumer = MultiConsumer(
                        self.redis,
                        num_consumers=consumer_count,
                        batch_size=settings.stream_consumer_batch_size,
                        block_ms=settings.stream_consumer_block_ms,
                    )
                else:
                    self.consumer = StreamConsumer(
                        self.redis,
                        batch_size=settings.stream_consumer_batch_size,
                        block_ms=settings.stream_consumer_block_ms,
                    )

        # Health checker (always needed)
        self.health_checker = HealthChecker(self.metrics, redis_client=self.redis)

        self._running = True
        logger.info(f"Pocketwatcher started successfully! (mode={self.mode})")

        # Send test messages (only in detect or all mode)
        if needs_detect:
            if self.discord and self.discord.is_configured():
                await self.discord.send_test_message()
            if self.telegram and self.telegram.is_configured():
                await self.telegram.send_test_message()

    async def stop(self):
        """Stop all components gracefully."""
        logger.info("Stopping Pocketwatcher...")
        self._running = False
        self._shutdown_event.set()

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Stop components
        # Stop config listener
        if self.processor:
            await self.processor.trigger_evaluator.stop_config_listener()

        if self.yellowstone:
            self.yellowstone.stop()
            await self.yellowstone.disconnect()

        if self.consumer:
            stop_result = self.consumer.stop()
            if asyncio.iscoroutine(stop_result):
                await stop_result

        if self.batch_consumer:
            await self.batch_consumer.stop()

        if self.delta_log:
            await self.delta_log.stop()

        if self.event_log:
            await self.event_log.stop()

        if self.alt_cache:
            await self.alt_cache.stop()

        if self.helius:
            await self.helius.stop()

        if self.discord:
            await self.discord.stop()

        if self.telegram:
            await self.telegram.stop()

        # Stop swap flusher (flushes remaining events to DB)
        if self.swap_flusher:
            await self.swap_flusher.stop()

        if self.redis:
            await self.redis.close()

        if self.postgres:
            await self.postgres.close()

        logger.info("Pocketwatcher stopped.")

    async def run(self):
        """Run the main application loop based on mode."""
        self._tasks = []

        # Determine which tasks to run based on mode
        needs_ingest = self.mode in ("all", "ingest")
        needs_consume = self.mode in ("all", "consume")
        needs_detect = self.mode in ("all", "detect")

        # Stats and health check (always run)
        self._tasks.append(asyncio.create_task(self._run_stats_loop()))
        self._tasks.append(asyncio.create_task(self.health_checker.health_check_loop()))

        # Ingest task
        if needs_ingest and self.yellowstone:
            self._tasks.append(asyncio.create_task(self._run_ingest()))

        # Consumer task
        if needs_consume:
            if self.high_throughput and self.batch_consumer:
                self._tasks.append(asyncio.create_task(self._run_batch_consumer()))
            elif self.consumer:
                self._tasks.append(asyncio.create_task(self._run_consumer()))

            # Swap flusher (needed for consume)
            if self.swap_flusher:
                self._tasks.append(asyncio.create_task(self.swap_flusher.run()))

            # Maintenance loop (needed for consume)
            self._tasks.append(asyncio.create_task(self._run_maintenance_loop()))

        # Detection loop
        if needs_detect and self.processor:
            self._tasks.append(asyncio.create_task(self._run_detection_loop()))

        logger.info(f"Started {len(self._tasks)} background tasks for mode={self.mode}")

        # Wait for shutdown
        await self._shutdown_event.wait()

    async def _run_ingest(self):
        """Run the Yellowstone stream ingest."""
        logger.info("Starting stream ingest...")

        async def on_transaction(tx):
            """Handle incoming transaction from stream."""
            # Push to Redis stream for buffered processing
            try:
                # Serialize transaction data
                import msgpack
                raw_data = msgpack.packb(self._tx_to_dict(tx))
                await self.redis.push_to_stream(raw_data)
            except Exception as e:
                logger.error(f"Failed to push transaction: {e}")

        async def on_error(error):
            """Handle stream errors."""
            logger.error(f"Stream error: {error}")

        try:
            await self.yellowstone.stream_transactions(
                on_transaction=on_transaction,
                on_error=on_error,
            )
        except asyncio.CancelledError:
            logger.info("Ingest task cancelled")

    def _tx_to_dict(self, tx) -> dict:
        """Convert transaction to dict for serialization."""
        import base58
        import time

        # Handle both protobuf and dict formats
        if isinstance(tx, dict):
            return tx

        # Yellowstone SubscribeUpdateTransaction structure:
        # tx.transaction = SubscribeUpdateTransactionInfo
        # tx.transaction.signature = bytes
        # tx.transaction.transaction = solana.storage.ConfirmedBlock.Transaction
        # tx.transaction.meta = TransactionStatusMeta
        # tx.slot = uint64
        signature = ""
        try:
            tx_info = getattr(tx, "transaction", None)  # SubscribeUpdateTransactionInfo
            inner_tx = getattr(tx_info, "transaction", None) if tx_info else None
            meta = getattr(tx_info, "meta", None) if tx_info else None

            # Convert signature bytes to base58 (best-effort)
            if tx_info and hasattr(tx_info, "signature"):
                try:
                    sig_bytes = bytes(tx_info.signature)
                    signature = base58.b58encode(sig_bytes).decode() if sig_bytes else ""
                except Exception as e:
                    logger.debug(f"Failed to decode signature: {e}")

            # Get account keys from the transaction message
            account_keys = []
            message = getattr(inner_tx, "message", None) if inner_tx else None
            if message and getattr(message, "account_keys", None):
                try:
                    for k in message.account_keys:
                        account_keys.append(base58.b58encode(bytes(k)).decode())
                except Exception as e:
                    logger.debug(f"Failed to parse account keys: {e}")

            # Get fee payer (first account key)
            fee_payer = account_keys[0] if account_keys else ""

            # Convert token balances - note: mint and owner are strings in TokenBalance
            pre_token_balances = []
            post_token_balances = []
            if meta:
                try:
                    for bal in getattr(meta, "pre_token_balances", []):
                        pre_token_balances.append({
                            "account_index": getattr(bal, "account_index", 0),
                            "mint": getattr(bal, "mint", ""),  # Already a string
                            "owner": getattr(bal, "owner", ""),  # Already a string
                            "amount": bal.ui_token_amount.amount if getattr(bal, "ui_token_amount", None) else "0",
                        })
                except Exception as e:
                    logger.debug(f"Failed to parse pre_token_balances: {e}")
                try:
                    for bal in getattr(meta, "post_token_balances", []):
                        post_token_balances.append({
                            "account_index": getattr(bal, "account_index", 0),
                            "mint": getattr(bal, "mint", ""),  # Already a string
                            "owner": getattr(bal, "owner", ""),  # Already a string
                            "amount": bal.ui_token_amount.amount if getattr(bal, "ui_token_amount", None) else "0",
                        })
                except Exception as e:
                    logger.debug(f"Failed to parse post_token_balances: {e}")

            # Estimate block_time from slot
            # Yellowstone doesn't include block_time in transaction updates.
            # We use current timestamp since we're processing in real-time.
            block_time = int(time.time())

            return {
                "signature": signature,
                "slot": getattr(tx, "slot", 0),
                "block_time": block_time,
                "fee_payer": fee_payer,
                "account_keys": account_keys,
                "pre_token_balances": pre_token_balances,
                "post_token_balances": post_token_balances,
                "pre_balances": list(getattr(meta, "pre_balances", [])) if meta else [],
                "post_balances": list(getattr(meta, "post_balances", [])) if meta else [],
                "fee": getattr(meta, "fee", 0) if meta else 0,
                "inner_instructions": [],  # Complex to convert, skip for now
            }
        except Exception as e:
            logger.warning(f"Failed to convert tx to dict: {e}")
            # Don't try to stringify protobuf - it can cause recursion
            return {
                "signature": signature,
                "slot": getattr(tx, "slot", 0),
                "error": str(e),
            }

    async def _run_consumer(self):
        """Run the Redis stream consumer."""
        logger.info("Starting stream consumer...")

        async def on_message(msg_id, raw_data):
            """Handle message from Redis stream."""
            import msgpack

            try:
                tx_data = msgpack.unpackb(raw_data)

                # Dedup check
                signature = tx_data.get("signature", "")
                if signature and await self.dedup.is_duplicate(signature):
                    return

                # Process transaction
                await self.processor.process_transaction(tx_data)

            except Exception as e:
                import traceback
                logger.error(f"Consumer error: {e}")
                logger.debug(f"Consumer traceback:\n{traceback.format_exc()}")

        async def on_error(msg_id, error):
            """Handle consumer errors."""
            logger.error(f"Consumer error for {msg_id}: {error}")

        try:
            await self.consumer.start(
                on_message=on_message,
                on_error=on_error,
            )
            if isinstance(self.consumer, MultiConsumer):
                await self._shutdown_event.wait()
        except asyncio.CancelledError:
            logger.info("Consumer task cancelled")

    async def _run_batch_consumer(self):
        """Run the high-throughput batch consumer with Redis pipelining."""
        logger.info("Starting batch consumer (high-throughput mode)...")

        async def on_batch(transactions, ctx):
            """Handle batch of transactions."""
            try:
                await self.batch_processor.process_batch(transactions, ctx)
            except Exception as e:
                import traceback
                logger.error(f"Batch processor error: {e}")
                logger.debug(f"Batch traceback:\n{traceback.format_exc()}")
                self.batch_processor.reset_pending()

        async def on_error(msg_id, error):
            """Handle batch consumer errors."""
            logger.error(f"Batch consumer error: {error}")

        try:
            await self.batch_consumer.start(
                on_batch=on_batch,
                on_error=on_error,
            )
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            logger.info("Batch consumer task cancelled")

    async def _run_detection_loop(self):
        """Run periodic detection trigger evaluation."""
        logger.info("Starting detection loop...")

        while self._running:
            try:
                # Throttle detection when backlog is high
                summary = self.metrics.get_summary()
                stream_len = summary.get("stream_length", 0)
                if stream_len >= settings.critical_stream_len:
                    await asyncio.sleep(5)
                    continue
                elif stream_len >= settings.degraded_stream_len:
                    sleep_s = 2
                    max_mints = 500
                else:
                    sleep_s = 1
                    max_mints = None

                await asyncio.sleep(sleep_s)

                # Get all active mints and evaluate triggers
                active_mints = await self.processor.counter_manager.get_active_mints()

                if max_mints is not None and len(active_mints) > max_mints:
                    # Limit evaluations under heavy load
                    active_mints = list(active_mints)[:max_mints]

                for mint in active_mints:
                    # Skip if already HOT
                    if await self.processor.state_manager.is_hot(mint):
                        continue

                    result = await self.processor.trigger_evaluator.evaluate(mint)
                    if result and result.triggered:
                        logger.info(f"Trigger fired: {result.trigger_name} for {mint[:8]}")
                        await self.processor._handle_trigger_result(mint, result)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Detection loop error: {e}")
                await asyncio.sleep(5)

    async def _run_stats_loop(self):
        """Publish live stats to Redis every 5 seconds for real-time dashboard."""
        logger.info("Starting stats loop (5s interval)...")

        while self._running:
            try:
                await asyncio.sleep(5)

                # Update metrics
                stream_info = await self.redis.get_stream_info()
                self.metrics.set_stream_length(stream_info.get("length", 0))

                hot_tokens = await self.processor.state_manager.get_hot_tokens()
                self.metrics.set_hot_token_count(len(hot_tokens))

                # Publish stats to Redis for API
                summary = self.metrics.get_summary()
                await self.redis.redis.set(
                    "pocketwatcher:live_stats",
                    json.dumps({
                        "tx_per_second": summary["tx_per_second"],
                        "swaps_detected": summary["swaps_detected"],
                        "hot_tokens_current": summary["hot_tokens_current"],
                        "processing_lag_seconds": summary["processing_lag_seconds"],
                        "stream_length": summary["stream_length"],
                        "uptime_seconds": summary["uptime_seconds"],
                        "transactions_processed": summary["transactions_processed"],
                        "alerts_sent": summary["alerts_sent"],
                        "updated_at": time.time(),
                    }),
                    ex=30  # Expire after 30s if worker stops
                )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Stats loop error: {e}")

    async def _run_maintenance_loop(self):
        """Run periodic maintenance tasks (cleanup, refresh, flush)."""
        logger.info("Starting maintenance loop (60s interval)...")

        while self._running:
            try:
                await asyncio.sleep(60)

                # Log stats
                summary = self.metrics.get_summary()
                logger.info(
                    f"Stats: {summary['tx_per_second']:.1f} tx/s, "
                    f"{summary['swaps_detected']} swaps, "
                    f"{summary['hot_tokens_current']} HOT tokens, "
                    f"lag: {summary['processing_lag_seconds']:.1f}s"
                )

                # Cleanup inactive mints (skip under heavy backlog)
                if summary["stream_length"] <= settings.degraded_stream_len:
                    await self.processor.counter_manager.cleanup_inactive()

                # Refresh HOT tokens
                await self.processor.state_manager.refresh_hot_tokens()

                # Flush event log
                await self.event_log.flush()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Maintenance loop error: {e}")


def setup_signal_handlers(app: Application):
    """Setup cross-platform signal handlers for graceful shutdown."""
    def handler(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info(f"Received {sig_name}, initiating graceful shutdown...")
        # Schedule shutdown in the event loop
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(lambda: asyncio.create_task(app.stop()))
        except RuntimeError:
            # No running loop yet
            pass

    # These work on both Unix and Windows
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    # Windows-specific: SIGBREAK (Ctrl+Break)
    if hasattr(signal, 'SIGBREAK'):
        signal.signal(signal.SIGBREAK, handler)


async def main(
    use_mock: bool = False,
    high_throughput: bool = True,
    mode: str = "all",
    consumer_name: Optional[str] = None,
):
    """Main entry point.

    Args:
        use_mock: Use mock stream instead of real Yellowstone
        high_throughput: Use batched consumer with Redis pipelining
        mode: Run mode - "all", "ingest", "consume", or "detect"
        consumer_name: Consumer name for XREADGROUP
    """
    app = Application(
        use_mock_stream=use_mock,
        high_throughput=high_throughput,
        mode=mode,
        consumer_name=consumer_name,
    )

    # Setup cross-platform signal handlers
    setup_signal_handlers(app)

    try:
        await app.start()
        await app.run()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise
    finally:
        await app.stop()


if __name__ == "__main__":
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Pocketwatcher - Solana CTO Monitor")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock stream instead of real Yellowstone connection"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Use legacy consumer (disable high-throughput mode)"
    )

    # Multi-process mode flags (mutually exclusive for clarity)
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--ingest-only",
        action="store_true",
        help="Run only Yellowstone ingest (no processing, no detection)"
    )
    mode_group.add_argument(
        "--consume-only",
        action="store_true",
        help="Run only stream consumer/processor (no ingest, no detection)"
    )
    mode_group.add_argument(
        "--detect-only",
        action="store_true",
        help="Run only detection/alerts (no ingest, no processing)"
    )

    parser.add_argument(
        "--consumer-name",
        type=str,
        default=None,
        help="Consumer name for XREADGROUP (default: auto-generated from hostname-pid)"
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Determine run mode
    if args.ingest_only:
        mode = "ingest"
    elif args.consume_only:
        mode = "consume"
    elif args.detect_only:
        mode = "detect"
    else:
        mode = "all"

    # Consumer name from arg, env, or auto-generate
    consumer_name = args.consumer_name or os.environ.get("CONSUMER_NAME")
    if not consumer_name and mode in ("consume", "all"):
        import socket
        consumer_name = f"parser-{socket.gethostname()}-{os.getpid()}"

    asyncio.run(main(
        use_mock=args.mock,
        high_throughput=not args.legacy,
        mode=mode,
        consumer_name=consumer_name,
    ))
