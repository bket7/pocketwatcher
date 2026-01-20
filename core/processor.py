"""Main transaction processor orchestrating all components."""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from models.events import MintTouchedEvent, SwapEventFull, TxDeltaRecord
from models.profiles import Alert, TokenProfile, TokenState
from parser.deltas import DeltaBuilder, WSOL_MINT
from parser.inference import SwapInference
from detection.counters import CounterManager
from detection.state import StateManager
from detection.triggers import TriggerEvaluator, TriggerResult
from enrichment.helius import HeliusClient
from enrichment.clustering import WalletClusterer
from enrichment.scoring import CTOScorer
from alerting.discord import DiscordAlerter
from alerting.telegram import TelegramAlerter
from storage.redis_client import RedisClient
from storage.postgres_client import PostgresClient
from storage.delta_log import DeltaLog
from storage.event_log import EventLog
from config.settings import settings
from .backpressure import BackpressureManager
from .monitoring import MetricsCollector

logger = logging.getLogger(__name__)


class TransactionProcessor:
    """
    Main transaction processor.

    Orchestrates:
    - Parsing transactions to deltas
    - Inferring swaps
    - Updating rolling counters
    - Managing token state
    - Triggering enrichment
    - Sending alerts
    """

    def __init__(
        self,
        redis_client: RedisClient,
        postgres_client: PostgresClient,
        delta_log: DeltaLog,
        event_log: EventLog,
        helius_client: HeliusClient,
        discord_alerter: DiscordAlerter,
        telegram_alerter: TelegramAlerter,
        metrics: MetricsCollector,
        known_programs: Optional[Set[str]] = None,
    ):
        # Storage
        self.redis = redis_client
        self.postgres = postgres_client
        self.delta_log = delta_log
        self.event_log = event_log

        # External services
        self.helius = helius_client
        self.discord = discord_alerter
        self.telegram = telegram_alerter

        # Metrics
        self.metrics = metrics

        # Known programs for unknown program discovery
        self.known_programs = known_programs or set()

        # Internal components
        self.delta_builder = DeltaBuilder()
        self.inference = SwapInference(self.delta_builder)
        self.counter_manager = CounterManager(redis_client)
        self.state_manager = StateManager(
            redis_client, postgres_client, delta_log
        )
        self.trigger_evaluator = TriggerEvaluator(self.counter_manager)
        self.clusterer = WalletClusterer(postgres_client)
        self.scorer = CTOScorer(self.clusterer)
        self.backpressure = BackpressureManager(redis_client)

        # Stats
        self._processed_count = 0
        self._swap_count = 0
        self._alert_count = 0
        self._unknown_programs: Dict[str, int] = {}

    async def initialize(self):
        """Initialize all components."""
        await self.trigger_evaluator.load_config()
        logger.info("TransactionProcessor initialized")

    async def process_transaction(self, tx_data: Dict[str, Any]):
        """
        Process a single transaction.

        This is the main entry point for transaction processing.
        """
        start_time = time.time()
        self._processed_count += 1

        # Extract basic info
        signature = tx_data.get("signature", "")
        slot = tx_data.get("slot", 0)
        block_time = tx_data.get("block_time", int(time.time()))
        fee_payer = tx_data.get("fee_payer", "")

        if not fee_payer:
            account_keys = tx_data.get("account_keys", [])
            fee_payer = account_keys[0] if account_keys else ""

        # Update backpressure
        await self.backpressure.update(block_time)
        bp_stats = self.backpressure.get_stats()
        self.metrics.set_processing_lag(bp_stats["processing_lag_seconds"])
        self.metrics.set_stream_length(bp_stats["stream_length"])

        # Build deltas
        token_deltas, sol_deltas = self.delta_builder.build_deltas(tx_data)

        # Extract metadata
        mints_touched = self.delta_builder.extract_mints_touched(token_deltas)
        programs_invoked = self.delta_builder.extract_program_ids(tx_data)

        # Track unknown programs
        await self._track_unknown_programs(programs_invoked, slot)

        # === ALWAYS: Emit MintTouchedEvent ===
        mint_event = MintTouchedEvent(
            signature=signature,
            slot=slot,
            block_time=block_time,
            fee_payer=fee_payer,
            mints_touched=mints_touched,
            programs_invoked=programs_invoked,
        )
        await self.event_log.append(mint_event)

        # === ALWAYS: Store TxDeltaRecord ===
        delta_record = TxDeltaRecord(
            signature=signature,
            slot=slot,
            block_time=block_time,
            fee_payer=fee_payer,
            programs_invoked=programs_invoked,
            token_deltas=[(o, m, amt) for (o, m), amt in token_deltas.items()],
            sol_deltas=sol_deltas,
            mints_touched=mints_touched,
            tx_fee=tx_data.get("fee", 0),
        )
        await self.delta_log.append(delta_record)

        # Update metrics
        self.metrics.inc("tx_processed_total")

        # === NORMAL mode: Full swap inference ===
        if self.backpressure.should_parse_full():
            candidates = self.delta_builder.get_candidate_users(token_deltas, fee_payer)
            swap = self.inference.infer_swap(token_deltas, sol_deltas, candidates)
            venue = self.inference.identify_venue(programs_invoked)

            if swap and swap.confidence >= settings.min_swap_confidence:
                self._swap_count += 1
                self.metrics.record_swap_detected(swap.side.value, venue)

                # Update state and counters
                await self._process_detected_swap(
                    mint=swap.base_mint,
                    swap=swap,
                    signature=signature,
                    slot=slot,
                    block_time=block_time,
                    venue=venue,
                )

        # Record processing time
        elapsed = time.time() - start_time
        self.metrics.record_processing_time(elapsed)

    async def _process_detected_swap(
        self,
        mint: str,
        swap,
        signature: str,
        slot: int,
        block_time: int,
        venue: str,
    ):
        """Process a detected swap event."""
        # Ensure token is at least WARM
        await self.state_manager.transition_to_warm(mint)

        # Calculate quote in SOL
        if swap.quote_mint == WSOL_MINT:
            quote_sol = swap.quote_amount / 1e9
        else:
            quote_sol = 0  # For USDC/USDT, would need price conversion

        # Update counters
        await self.counter_manager.record_swap(
            mint=mint,
            user_wallet=swap.user_wallet,
            quote_amount_sol=quote_sol,
            side=swap.side.value,
        )

        # Track wallet in clusterer
        self.clusterer.add_wallet(
            swap.user_wallet,
            volume_sol=quote_sol,
            buy_count=1 if swap.side.value == "buy" else 0,
        )

        # Store full swap event if token is HOT
        if await self.state_manager.is_hot(mint):
            swap_event = SwapEventFull(
                signature=signature,
                slot=slot,
                block_time=block_time,
                venue=venue,
                user_wallet=swap.user_wallet,
                side=swap.side,
                base_mint=swap.base_mint,
                base_amount=swap.base_amount,
                quote_mint=swap.quote_mint,
                quote_amount=swap.quote_amount,
                confidence=swap.confidence,
            )
            await self.postgres.insert_swap_event(swap_event)

        # Evaluate triggers
        await self._evaluate_triggers(mint)

    async def _evaluate_triggers(self, mint: str):
        """Evaluate triggers for a mint and handle HOT transitions."""
        # Skip if already HOT
        if await self.state_manager.is_hot(mint):
            return

        result = await self.trigger_evaluator.evaluate(mint)

        if result and result.triggered:
            # Transition to HOT
            await self.state_manager.transition_to_hot(
                mint,
                result.reason,
                trigger_backfill=True,
            )
            self.metrics.record_hot_token(result.trigger_name)

            # Create and send alert
            await self._create_alert(mint, result)

    async def _create_alert(self, mint: str, trigger_result: TriggerResult):
        """Create and send an alert for a HOT token."""
        self._alert_count += 1

        # Get token metadata
        token_profile = await self.postgres.get_token_profile(mint)
        token_name = token_profile.name if token_profile else None
        token_symbol = token_profile.symbol if token_profile else None

        # Get top buyers
        top_buyers = await self.postgres.get_top_buyers(mint, limit=5)

        # Calculate CTO score
        cto_score = self.scorer.score_token(
            trigger_result.stats,
            top_buyers,
        )

        # Generate cluster summary
        buyer_wallets = [b["user_wallet"] for b in top_buyers]
        cluster_summary = self.clusterer.generate_summary(buyer_wallets)

        # Check enrichment status
        enrichment_degraded = self.helius.is_degraded()

        # Create alert
        alert = Alert(
            mint=mint,
            token_name=token_name,
            token_symbol=token_symbol,
            trigger_name=trigger_result.trigger_name,
            trigger_reason=trigger_result.reason,
            buy_count_5m=trigger_result.stats.buy_count,
            unique_buyers_5m=trigger_result.stats.unique_buyers,
            volume_sol_5m=trigger_result.stats.volume_sol,
            buy_sell_ratio_5m=trigger_result.stats.buy_sell_ratio,
            top_buyers=top_buyers,
            cluster_summary=cluster_summary,
            enrichment_degraded=enrichment_degraded,
            created_at=datetime.utcnow(),
        )

        # Store alert
        alert_id = await self.postgres.insert_alert(alert)
        alert.id = alert_id

        # Send to channels
        await self._send_alert(alert, cto_score)

    async def _send_alert(self, alert: Alert, cto_score):
        """Send alert to configured channels."""
        # Discord
        if self.discord.is_configured():
            success = await self.discord.send_alert(alert, cto_score)
            if success:
                await self.postgres.update_alert_delivery(alert.id, discord=True)
                self.metrics.record_alert_sent("discord")

        # Telegram
        if self.telegram.is_configured():
            success = await self.telegram.send_alert(alert, cto_score)
            if success:
                await self.postgres.update_alert_delivery(alert.id, telegram=True)
                self.metrics.record_alert_sent("telegram")

        logger.info(
            f"Alert sent for {alert.mint[:8]}: {alert.trigger_name} "
            f"(CTO: {cto_score.total_score:.0%})"
        )

    async def _track_unknown_programs(self, programs: Set[str], slot: int):
        """Track unknown program occurrences."""
        unknown = programs - self.known_programs

        if not unknown:
            return

        known_in_tx = programs & self.known_programs

        for prog_id in unknown:
            self._unknown_programs[prog_id] = self._unknown_programs.get(prog_id, 0) + 1

            # Track in Redis
            await self.redis.track_program(prog_id, slot, known_in_tx)

            # Alert if threshold reached
            count = self._unknown_programs[prog_id]
            if count == 100:  # Alert at 100 occurrences
                logger.warning(
                    f"Unknown program {prog_id} seen {count} times, "
                    f"co-occurs with {known_in_tx}"
                )

    async def reprocess_delta_record(self, record: TxDeltaRecord):
        """
        Reprocess a TxDeltaRecord for backfill.

        Called when a token becomes HOT to backfill swap events.
        """
        # Reconstruct deltas
        token_deltas = {(o, m): amt for o, m, amt in record.token_deltas}
        sol_deltas = record.sol_deltas

        # Infer swap
        candidates = self.delta_builder.get_candidate_users(token_deltas, record.fee_payer)
        swap = self.inference.infer_swap(token_deltas, sol_deltas, candidates)

        if swap and swap.confidence >= settings.min_swap_confidence:
            venue = self.inference.identify_venue(record.programs_invoked)

            swap_event = SwapEventFull(
                signature=record.signature,
                slot=record.slot,
                block_time=record.block_time,
                venue=venue,
                user_wallet=swap.user_wallet,
                side=swap.side,
                base_mint=swap.base_mint,
                base_amount=swap.base_amount,
                quote_mint=swap.quote_mint,
                quote_amount=swap.quote_amount,
                confidence=swap.confidence,
            )
            await self.postgres.insert_swap_event(swap_event)

    async def run_enrichment(self, mint: str):
        """
        Run enrichment for a HOT token.

        Traces funding for top buyers and updates clusters.
        """
        if not self.backpressure.should_enrich():
            logger.info(f"Skipping enrichment for {mint[:8]} (backpressure)")
            return

        # Get top buyers
        top_buyers = await self.postgres.get_top_buyers(mint, limit=10)

        for buyer in top_buyers:
            wallet = buyer["user_wallet"]

            # Trace funding
            funding = await self.helius.trace_funding(wallet, max_hops=2)

            if funding:
                # Link to funder in clusterer
                ultimate_funder = funding["ultimate_funder"]
                self.clusterer.link_funding(wallet, ultimate_funder)

                # Update wallet profile
                profile = await self.postgres.get_wallet_profile(wallet)
                if profile:
                    profile.funded_by = ultimate_funder
                    profile.funding_hop = funding["hops"]
                    await self.postgres.upsert_wallet_profile(profile)

        # Persist clusters
        await self.clusterer.persist_all_clusters()

    def get_stats(self) -> dict:
        """Get processor statistics."""
        return {
            "processed_count": self._processed_count,
            "swap_count": self._swap_count,
            "alert_count": self._alert_count,
            "detection_rate_pct": (
                self._swap_count / self._processed_count * 100
                if self._processed_count > 0
                else 0
            ),
            "unknown_programs_tracked": len(self._unknown_programs),
            "delta_builder": self.delta_builder.get_stats(),
            "inference": self.inference.get_stats(),
            "counters": self.counter_manager.get_manager_stats(),
            "state": self.state_manager.get_stats(),
            "triggers": self.trigger_evaluator.get_stats(),
            "backpressure": self.backpressure.get_stats(),
        }
