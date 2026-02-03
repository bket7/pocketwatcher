"""
Batch transaction processor for high-throughput processing.

Works with BatchConsumer to process transactions with minimal Redis RTTs.
"""

import logging
import time
from typing import Any, Dict, List, Optional, Set

from models.events import MintTouchedEvent, SwapEventFull, TxDeltaRecord
from models.profiles import TokenState
from parser.deltas import DeltaBuilder, WSOL_MINT
from parser.inference import SwapInference
from storage.swap_queue import SwapEventQueue
from config.settings import settings

logger = logging.getLogger(__name__)


class BatchProcessor:
    """
    Processes batches of transactions with minimal Redis overhead.

    Designed to work with BatchConsumer for high throughput.
    All Redis operations are accumulated and executed via BatchContext.
    """

    def __init__(
        self,
        delta_log=None,
        event_log=None,
        swap_queue: Optional[SwapEventQueue] = None,
        metrics=None,
        known_programs: Optional[Set[str]] = None,
        counter_manager=None,
    ):
        # Storage (local writes only)
        self.delta_log = delta_log
        self.event_log = event_log
        self.swap_queue = swap_queue

        # Metrics
        self.metrics = metrics

        # Counter manager for tracking active mints (for detection loop)
        self.counter_manager = counter_manager

        # Known programs for unknown program discovery
        self.known_programs = known_programs or set()

        # Internal components (pure Python, no I/O)
        self.delta_builder = DeltaBuilder()
        self.inference = SwapInference(self.delta_builder)

        # Stats
        self._processed_count = 0
        self._swap_count = 0
        self._hot_swap_count = 0

        # Local state cache (token -> state)
        self._state_cache: Dict[str, TokenState] = {}

        # Last batch sizes (for stats only)
        self._last_pending_delta_count = 0
        self._last_pending_event_count = 0

    async def process_batch(
        self,
        transactions: List[Dict[str, Any]],
        ctx,  # BatchContext from batch_consumer
    ):
        """
        Process a batch of transactions.

        All heavy work is pure Python (no I/O).
        Counter updates are queued to ctx for batched Redis execution.
        """
        start_time = time.time()

        pending_delta_records: List[TxDeltaRecord] = []
        pending_mint_events: List[MintTouchedEvent] = []

        for tx_data in transactions:
            await self._process_single(
                tx_data,
                ctx,
                pending_delta_records,
                pending_mint_events,
            )

        # Batch write delta records and mint events (local I/O, not Redis)
        if self.delta_log and pending_delta_records:
            await self.delta_log.append_batch(pending_delta_records)

        if self.event_log and pending_mint_events:
            await self.event_log.append_batch(pending_mint_events)

        self._last_pending_delta_count = len(pending_delta_records)
        self._last_pending_event_count = len(pending_mint_events)

        # Record batch processing time
        elapsed = time.time() - start_time
        if self.metrics:
            self.metrics.record_batch_time(elapsed, len(transactions))

    async def _process_single(
        self,
        tx_data: Dict[str, Any],
        ctx,  # BatchContext
        pending_delta_records: List[TxDeltaRecord],
        pending_mint_events: List[MintTouchedEvent],
    ):
        """Process a single transaction within a batch."""
        self._processed_count += 1

        # Extract basic info
        signature = tx_data.get("signature", "")
        slot = tx_data.get("slot", 0)
        block_time = tx_data.get("block_time", int(time.time()))
        fee_payer = tx_data.get("fee_payer", "")

        if not fee_payer:
            account_keys = tx_data.get("account_keys", [])
            fee_payer = account_keys[0] if account_keys else ""

        # Build deltas (pure Python)
        token_deltas, sol_deltas = self.delta_builder.build_deltas(tx_data)

        # Extract metadata (pure Python)
        mints_touched = self.delta_builder.extract_mints_touched(token_deltas)
        programs_invoked = self.delta_builder.extract_program_ids(tx_data)

        # Create MintTouchedEvent (accumulate for batch write)
        mint_event = MintTouchedEvent(
            signature=signature,
            slot=slot,
            block_time=block_time,
            fee_payer=fee_payer,
            mints_touched=mints_touched,
            programs_invoked=programs_invoked,
        )
        pending_mint_events.append(mint_event)

        # Create TxDeltaRecord (accumulate for batch write)
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
        pending_delta_records.append(delta_record)

        # Update metrics
        if self.metrics:
            self.metrics.inc("tx_processed_total")

        # Swap inference (pure Python)
        candidates = self.delta_builder.get_candidate_users(token_deltas, fee_payer)
        swap = self.inference.infer_swap(token_deltas, sol_deltas, candidates)
        venue = self.inference.identify_venue(programs_invoked)

        if swap and swap.confidence >= settings.min_swap_confidence:
            self._swap_count += 1
            if self.metrics:
                self.metrics.record_swap_detected(swap.side.value, venue)

            # Process the detected swap
            await self._process_swap(
                mint=swap.base_mint,
                swap=swap,
                signature=signature,
                slot=slot,
                block_time=block_time,
                venue=venue,
                ctx=ctx,
            )

    async def _process_swap(
        self,
        mint: str,
        swap,
        signature: str,
        slot: int,
        block_time: int,
        venue: str,
        ctx,  # BatchContext
    ):
        """Process a detected swap, queuing updates to BatchContext."""
        # Calculate quote in SOL
        if swap.quote_mint == WSOL_MINT:
            quote_sol = swap.quote_amount / 1e9
        else:
            quote_sol = 0

        # Queue counter update (batched to Redis)
        ctx.queue_counter_update(
            mint=mint,
            user_wallet=swap.user_wallet,
            quote_amount_sol=quote_sol,
            side=swap.side.value,
        )

        # Register mint with counter_manager for detection loop to see
        if self.counter_manager:
            self.counter_manager._active_mints.add(mint)

        # Mark token as at least WARM in local cache
        if mint not in self._state_cache:
            self._state_cache[mint] = TokenState.WARM

        # Store full swap event if token is HOT
        if ctx.is_hot(mint):
            self._hot_swap_count += 1

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
                mcap_at_swap=None,  # Will be calculated by trigger evaluator
            )

            # Queue to swap queue (non-blocking DB write)
            if self.swap_queue:
                await self.swap_queue.put(swap_event)

    def get_stats(self) -> dict:
        """Get processor statistics."""
        return {
            "processed_count": self._processed_count,
            "swap_count": self._swap_count,
            "hot_swap_count": self._hot_swap_count,
            "detection_rate_pct": (
                self._swap_count / self._processed_count * 100
                if self._processed_count > 0
                else 0
            ),
            "delta_builder": self.delta_builder.get_stats(),
            "inference": self.inference.get_stats(),
            "pending_deltas": self._last_pending_delta_count,
            "pending_events": self._last_pending_event_count,
            "state_cache_size": len(self._state_cache),
        }

    def reset_pending(self):
        """Reset pending batches (called on error)."""
        self._last_pending_delta_count = 0
        self._last_pending_event_count = 0
