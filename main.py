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
from stream.dedup import DedupFilter
from parser.alt_cache import ALTCache
from enrichment.helius import HeliusClient
from alerting.discord import DiscordAlerter
from alerting.telegram import TelegramAlerter
from core.processor import TransactionProcessor
from core.monitoring import MetricsCollector, HealthChecker

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

    def __init__(self, use_mock_stream: bool = False):
        self.use_mock_stream = use_mock_stream
        self._running = False
        self._shutdown_event = asyncio.Event()

        # Components (initialized in start())
        self.redis: Optional[RedisClient] = None
        self.postgres: Optional[PostgresClient] = None
        self.delta_log: Optional[DeltaLog] = None
        self.event_log: Optional[EventLog] = None
        self.yellowstone: Optional[YellowstoneClient] = None
        self.consumer: Optional[Union[StreamConsumer, MultiConsumer]] = None
        self.dedup: Optional[DedupFilter] = None
        self.alt_cache: Optional[ALTCache] = None
        self.helius: Optional[HeliusClient] = None
        self.discord: Optional[DiscordAlerter] = None
        self.telegram: Optional[TelegramAlerter] = None
        self.processor: Optional[TransactionProcessor] = None
        self.metrics: Optional[MetricsCollector] = None
        self.health_checker: Optional[HealthChecker] = None

        # Tasks
        self._tasks = []

    async def start(self):
        """Start all components."""
        logger.info("Starting Pocketwatcher...")

        # Initialize metrics
        self.metrics = MetricsCollector()

        # Initialize storage
        logger.info("Connecting to Redis...")
        self.redis = RedisClient()
        await self.redis.connect()

        logger.info("Connecting to PostgreSQL...")
        self.postgres = PostgresClient()
        await self.postgres.connect()

        logger.info("Initializing logs...")
        self.delta_log = DeltaLog()
        await self.delta_log.start()

        self.event_log = EventLog()
        await self.event_log.start()

        # Initialize stream client
        logger.info("Initializing stream client...")
        if self.use_mock_stream:
            self.yellowstone = MockYellowstoneClient()
        else:
            self.yellowstone = YellowstoneClient()

        await self.yellowstone.load_programs()

        # Initialize dedup
        self.dedup = DedupFilter(self.redis)

        # Initialize ALT cache
        self.alt_cache = ALTCache()
        await self.alt_cache.start()

        # Initialize enrichment
        logger.info("Initializing Helius client...")
        self.helius = HeliusClient()
        await self.helius.start()

        # Initialize alerting
        logger.info("Initializing alerters...")
        self.discord = DiscordAlerter()
        await self.discord.start()

        self.telegram = TelegramAlerter()
        await self.telegram.start()

        # Initialize processor
        logger.info("Initializing transaction processor...")
        self.processor = TransactionProcessor(
            redis_client=self.redis,
            postgres_client=self.postgres,
            delta_log=self.delta_log,
            event_log=self.event_log,
            helius_client=self.helius,
            discord_alerter=self.discord,
            telegram_alerter=self.telegram,
            metrics=self.metrics,
            known_programs=self.yellowstone.known_programs,
        )
        await self.processor.initialize()

        # Start config hot-reload listener
        await self.processor.trigger_evaluator.start_config_listener()

        # Initialize consumer
        consumer_count = max(1, settings.stream_consumer_count)
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

        # Initialize health checker
        self.health_checker = HealthChecker(self.metrics, redis_client=self.redis)

        self._running = True
        logger.info("Pocketwatcher started successfully!")

        # Send test messages
        if self.discord.is_configured():
            await self.discord.send_test_message()
        if self.telegram.is_configured():
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

        if self.redis:
            await self.redis.close()

        if self.postgres:
            await self.postgres.close()

        logger.info("Pocketwatcher stopped.")

    async def run(self):
        """Run the main application loop."""
        # Start background tasks
        self._tasks = [
            asyncio.create_task(self._run_ingest()),
            asyncio.create_task(self._run_consumer()),
            asyncio.create_task(self._run_detection_loop()),
            asyncio.create_task(self._run_maintenance_loop()),
            asyncio.create_task(self.health_checker.health_check_loop()),
        ]

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
        try:
            tx_info = tx.transaction  # SubscribeUpdateTransactionInfo
            inner_tx = tx_info.transaction  # The actual Transaction proto
            meta = tx_info.meta  # TransactionStatusMeta

            # Convert signature bytes to base58
            sig_bytes = bytes(tx_info.signature)
            signature = base58.b58encode(sig_bytes).decode() if sig_bytes else ""

            # Get account keys from the transaction message
            account_keys = []
            if inner_tx and inner_tx.message:
                for k in inner_tx.message.account_keys:
                    account_keys.append(base58.b58encode(bytes(k)).decode())

            # Get fee payer (first account key)
            fee_payer = account_keys[0] if account_keys else ""

            # Convert token balances - note: mint and owner are strings in TokenBalance
            pre_token_balances = []
            post_token_balances = []
            if meta:
                for bal in meta.pre_token_balances:
                    pre_token_balances.append({
                        "account_index": bal.account_index,
                        "mint": bal.mint,  # Already a string
                        "owner": bal.owner,  # Already a string
                        "amount": bal.ui_token_amount.amount if bal.ui_token_amount else "0",
                    })
                for bal in meta.post_token_balances:
                    post_token_balances.append({
                        "account_index": bal.account_index,
                        "mint": bal.mint,  # Already a string
                        "owner": bal.owner,  # Already a string
                        "amount": bal.ui_token_amount.amount if bal.ui_token_amount else "0",
                    })

            # Estimate block_time from slot
            # Yellowstone doesn't include block_time in transaction updates.
            # We use current timestamp since we're processing in real-time.
            # For historical accuracy, block_time = reference_time + (slot - reference_slot) * 0.4
            # But current time is accurate enough for real-time streaming.
            block_time = int(time.time())

            return {
                "signature": signature,
                "slot": tx.slot,
                "block_time": block_time,
                "fee_payer": fee_payer,
                "account_keys": account_keys,
                "pre_token_balances": pre_token_balances,
                "post_token_balances": post_token_balances,
                "pre_balances": list(meta.pre_balances) if meta else [],
                "post_balances": list(meta.post_balances) if meta else [],
                "fee": meta.fee if meta else 0,
                "inner_instructions": [],  # Complex to convert, skip for now
            }
        except Exception as e:
            logger.warning(f"Failed to convert tx to dict: {e}")
            # Don't try to stringify protobuf - it can cause recursion
            return {"signature": "unknown", "error": str(e)}

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

    async def _run_detection_loop(self):
        """Run periodic detection trigger evaluation."""
        logger.info("Starting detection loop...")

        while self._running:
            try:
                await asyncio.sleep(1)  # Evaluate every second

                # Get all active mints and evaluate triggers
                active_mints = await self.processor.counter_manager.get_active_mints()

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

    async def _run_maintenance_loop(self):
        """Run periodic maintenance tasks."""
        logger.info("Starting maintenance loop...")

        while self._running:
            try:
                await asyncio.sleep(60)  # Run every minute

                # Update metrics
                stream_info = await self.redis.get_stream_info()
                self.metrics.set_stream_length(stream_info.get("length", 0))

                hot_tokens = await self.processor.state_manager.get_hot_tokens()
                self.metrics.set_hot_token_count(len(hot_tokens))

                # Log stats and publish to Redis for API
                summary = self.metrics.get_summary()
                logger.info(
                    f"Stats: {summary['tx_per_second']:.1f} tx/s, "
                    f"{summary['swaps_detected']} swaps, "
                    f"{summary['hot_tokens_current']} HOT tokens, "
                    f"lag: {summary['processing_lag_seconds']:.1f}s"
                )

                # Publish stats to Redis so API can read them
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
                    ex=120  # Expire after 2 minutes if worker stops
                )

                # Cleanup inactive mints
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


async def main(use_mock: bool = False):
    """Main entry point."""
    app = Application(use_mock_stream=use_mock)

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

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    asyncio.run(main(use_mock=args.mock))
