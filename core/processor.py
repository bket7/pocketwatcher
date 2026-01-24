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
        self.trigger_evaluator = TriggerEvaluator(
            self.counter_manager, redis_client=redis_client
        )
        self.clusterer = WalletClusterer(postgres_client)
        self.scorer = CTOScorer(self.clusterer)
        self.backpressure = BackpressureManager(redis_client)

        # Stats
        self._processed_count = 0
        self._swap_count = 0
        self._alert_count = 0
        self._unknown_programs: Dict[str, int] = {}

        # Cache for token supply (mint -> {supply, decimals})
        self._token_supply_cache: Dict[str, Dict[str, Any]] = {}

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

        # Calculate mcap at swap time for ALL swaps (not just HOT)
        # This is critical for having mcap data when alerts are created
        supply_info = await self._get_token_supply(mint)
        mcap_at_swap = None
        if swap.quote_mint == WSOL_MINT and swap.base_amount > 0:
            mcap_at_swap = self._calculate_mcap_at_swap(
                swap.quote_amount,
                swap.base_amount,
                swap.quote_mint,
                supply_info,
            )
            # Store latest mcap in Redis for quick alert lookups
            if mcap_at_swap is not None:
                price_per_unit = (swap.quote_amount / 1e9) / swap.base_amount
                decimals = supply_info.get("decimals", 9) if supply_info else 9
                price_sol = price_per_unit * (10 ** decimals)
                await self.redis.set_token_mcap(mint, mcap_at_swap, price_sol)

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
                mcap_at_swap=mcap_at_swap,
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
            await self._handle_trigger_result(mint, result)

    async def _handle_trigger_result(self, mint: str, result: TriggerResult):
        """Handle a trigger result - transition to HOT and create alert."""
        # Skip if already HOT (may have been triggered by another path)
        if await self.state_manager.is_hot(mint):
            return

        # Minimum mcap filter - skip micro-cap tokens that almost always rug
        # 500 SOL mcap ≈ $60K at $120/SOL
        MIN_MCAP_SOL = 500
        redis_mcap = await self.redis.get_token_mcap(mint)
        if redis_mcap and redis_mcap.get("mcap_sol"):
            mcap = redis_mcap["mcap_sol"]
            if mcap < MIN_MCAP_SOL:
                logger.info(f"Skipping {mint[:8]} - mcap {mcap:.0f} SOL below minimum {MIN_MCAP_SOL}")
                return

        # Transition to HOT
        await self.state_manager.transition_to_hot(
            mint,
            result.reason,
            trigger_backfill=True,
        )
        self.metrics.record_hot_token(result.trigger_name)

        # Create and send alert
        await self._create_alert(mint, result)

    async def _get_token_supply(self, mint: str) -> Optional[Dict[str, Any]]:
        """Get cached or fetch token supply info."""
        if mint in self._token_supply_cache:
            return self._token_supply_cache[mint]

        try:
            supply_info = await self.helius.get_token_supply(mint)
            if supply_info:
                self._token_supply_cache[mint] = supply_info
                return supply_info
        except Exception as e:
            logger.debug(f"Failed to get token supply for {mint[:8]}: {e}")

        return None

    def _calculate_mcap_at_swap(
        self,
        quote_amount: int,
        base_amount: int,
        quote_mint: str,
        supply_info: Optional[Dict[str, Any]],
    ) -> Optional[float]:
        """
        Calculate market cap at swap time from swap price and token supply.

        Returns mcap in SOL, or None if calculation not possible.
        """
        if not supply_info or quote_mint != WSOL_MINT:
            return None

        if base_amount <= 0:
            return None

        try:
            raw_supply = supply_info["supply"]
            decimals = supply_info["decimals"]

            # Price per base unit in SOL
            price_per_unit = (quote_amount / 1e9) / base_amount

            # Price per whole token in SOL
            price_sol = price_per_unit * (10 ** decimals)

            # Supply in whole tokens
            supply_whole_tokens = raw_supply / (10 ** decimals)

            # Market cap in SOL
            mcap_sol = price_sol * supply_whole_tokens

            return mcap_sol
        except Exception as e:
            logger.debug(f"Failed to calculate mcap at swap: {e}")
            return None

    async def _calculate_price_and_mcap(self, mint: str) -> Dict[str, Any]:
        """
        Calculate price and market cap for a token at alert time.

        Uses Redis-cached mcap from recent swaps (fast and always available),
        falls back to postgres if needed.

        Returns dict with price_sol, mcap_sol, token_supply (or None values if unavailable).
        """
        result = {"price_sol": None, "mcap_sol": None, "token_supply": None}

        try:
            # FIRST: Try Redis for cached mcap (set by _process_detected_swap)
            # This is the most reliable source since it's set in real-time
            redis_mcap = await self.redis.get_token_mcap(mint)
            if redis_mcap:
                result["mcap_sol"] = redis_mcap["mcap_sol"]
                result["price_sol"] = redis_mcap.get("price_sol")
                logger.info(
                    f"Got mcap from Redis for {mint[:8]}: {result['mcap_sol']:.2f} SOL"
                )

            # Get token supply for completeness
            supply_info = await self.helius.get_token_supply(mint)
            if supply_info:
                result["token_supply"] = supply_info["supply"]

            # If Redis didn't have mcap, try postgres as fallback
            if result["mcap_sol"] is None:
                try:
                    swaps = await asyncio.wait_for(
                        self.postgres.get_recent_swaps(mint, limit=5),
                        timeout=2.0
                    )
                    buys = [s for s in swaps if s.side.value == "buy" and s.quote_mint == WSOL_MINT]

                    if buys and supply_info:
                        total_quote = sum(s.quote_amount for s in buys)
                        total_base = sum(s.base_amount for s in buys)
                        decimals = supply_info["decimals"]
                        raw_supply = supply_info["supply"]

                        if total_base > 0:
                            price_per_unit = (total_quote / 1e9) / total_base
                            price_sol = price_per_unit * (10 ** decimals)
                            supply_whole_tokens = raw_supply / (10 ** decimals)
                            mcap_sol = price_sol * supply_whole_tokens

                            result["price_sol"] = price_sol
                            result["mcap_sol"] = mcap_sol

                            logger.info(
                                f"Calculated mcap from postgres for {mint[:8]}: {mcap_sol:.2f} SOL"
                            )
                except asyncio.TimeoutError:
                    logger.debug(f"Postgres swap query timed out for {mint[:8]}")
                except Exception as e:
                    logger.debug(f"Failed to get swaps from postgres for {mint[:8]}: {e}")

        except Exception as e:
            logger.warning(f"Failed to calculate price/mcap for {mint[:8]}: {e}")

        return result

    async def _create_alert(self, mint: str, trigger_result: TriggerResult):
        """Create and send an alert for a HOT token."""
        logger.info(f"Creating alert for {mint[:8]} (trigger: {trigger_result.trigger_name})")
        self._alert_count += 1

        try:
            # Get token metadata from profile first
            token_profile = await self.postgres.get_token_profile(mint)
            token_name = token_profile.name if token_profile else None
            token_symbol = token_profile.symbol if token_profile else None
            token_image = None

            # Try DexScreener first for metadata (free, no credits)
            dex_meta = await self.helius.get_token_metadata_dexscreener(mint)
            if dex_meta:
                token_name = token_name or dex_meta.get("name")
                token_symbol = token_symbol or dex_meta.get("symbol")
                token_image = dex_meta.get("image")

            # If still missing name/symbol, try Helius DAS API (works for new pump.fun tokens)
            if not token_name or not token_symbol:
                das_meta = await self.helius.get_token_metadata_das(mint)
                if das_meta:
                    token_name = token_name or das_meta.get("name")
                    token_symbol = token_symbol or das_meta.get("symbol")
                    token_image = token_image or das_meta.get("image")

            # Get dominant venue
            venue = await self.postgres.get_dominant_venue(mint)
            # Detect pump.fun from mint address as fallback
            if not venue and mint.endswith("pump"):
                venue = "pump"

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

            # Calculate price and market cap at alert time
            price_mcap = await self._calculate_price_and_mcap(mint)

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
                price_sol=price_mcap["price_sol"],
                mcap_sol=price_mcap["mcap_sol"],
                token_supply=price_mcap["token_supply"],
                venue=venue,
                token_image=token_image,
            )

            # Store alert
            alert_id = await self.postgres.insert_alert(alert)
            alert.id = alert_id
            logger.info(f"Alert {alert_id} stored for {mint[:8]}")

            # Send to channels
            await self._send_alert(alert, cto_score)

        except Exception as e:
            import traceback
            logger.error(f"Failed to create alert for {mint[:8]}: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")

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

            # Calculate mcap at swap time (supply should be cached from alert creation)
            supply_info = await self._get_token_supply(swap.base_mint)
            mcap_at_swap = self._calculate_mcap_at_swap(
                swap.quote_amount,
                swap.base_amount,
                swap.quote_mint,
                supply_info,
            )

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
                mcap_at_swap=mcap_at_swap,
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
