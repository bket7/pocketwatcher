"""Token state machine for HOT/WARM/COLD management."""

import asyncio
import logging
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set

from models.profiles import TokenProfile, TokenState
from storage.redis_client import RedisClient
from storage.postgres_client import PostgresClient
from storage.delta_log import DeltaLog

logger = logging.getLogger(__name__)


class StateManager:
    """
    Manages token state transitions (COLD -> WARM -> HOT).

    State machine:
    - COLD: Default. Aggregates only.
    - WARM: Per-swap events stored for 30-60 min. First activity.
    - HOT: Full enrichment + clustering. Crossed detection thresholds.

    Handles:
    - State transitions
    - Backfill triggers when token becomes HOT
    - HOT token expiry management
    """

    def __init__(
        self,
        redis_client: RedisClient,
        postgres_client: PostgresClient,
        delta_log: DeltaLog,
        hot_ttl_seconds: int = 3600,
        warm_ttl_seconds: int = 1800,
    ):
        self.redis = redis_client
        self.postgres = postgres_client
        self.delta_log = delta_log
        self.hot_ttl = hot_ttl_seconds
        self.warm_ttl = warm_ttl_seconds

        self._state_cache: Dict[str, TokenState] = {}
        self._hot_callbacks: List[Callable] = []
        self._backfill_queue: asyncio.Queue = asyncio.Queue()

    async def get_state(self, mint: str) -> TokenState:
        """Get current token state."""
        # Check cache first
        if mint in self._state_cache:
            return self._state_cache[mint]

        # Check Redis for HOT
        if await self.redis.is_token_hot(mint):
            self._state_cache[mint] = TokenState.HOT
            return TokenState.HOT

        # Check Postgres
        profile = await self.postgres.get_token_profile(mint)
        if profile:
            self._state_cache[mint] = profile.state
            return profile.state

        # Default to COLD
        return TokenState.COLD

    async def transition_to_warm(self, mint: str):
        """Transition token to WARM state (first activity)."""
        current = await self.get_state(mint)

        if current == TokenState.COLD:
            self._state_cache[mint] = TokenState.WARM

            # Create or update profile in Postgres
            profile = TokenProfile(
                mint=mint,
                state=TokenState.WARM,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
            )
            await self.postgres.upsert_token_profile(profile)

            logger.debug(f"Token {mint[:8]}... transitioned to WARM")

    async def transition_to_hot(
        self,
        mint: str,
        reason: str,
        trigger_backfill: bool = True
    ):
        """
        Transition token to HOT state.

        Args:
            mint: Token mint address
            reason: Trigger reason for alert
            trigger_backfill: Whether to backfill from delta log
        """
        current = await self.get_state(mint)

        if current == TokenState.HOT:
            # Already HOT, refresh TTL
            await self.redis.mark_token_hot(mint, self.hot_ttl)
            return

        # Update state
        self._state_cache[mint] = TokenState.HOT

        # Mark HOT in Redis (with expiry)
        await self.redis.mark_token_hot(mint, self.hot_ttl)

        # Update Postgres
        await self.postgres.update_token_state(mint, TokenState.HOT, reason)

        logger.info(f"Token {mint[:8]}... became HOT: {reason}")

        # Trigger backfill from delta log
        if trigger_backfill:
            await self._backfill_queue.put(mint)

        # Notify callbacks
        for callback in self._hot_callbacks:
            try:
                await callback(mint, reason)
            except Exception as e:
                logger.error(f"HOT callback error: {e}")

    async def transition_to_cold(self, mint: str):
        """Transition token back to COLD (HOT expired)."""
        self._state_cache[mint] = TokenState.COLD
        await self.postgres.update_token_state(mint, TokenState.COLD)
        logger.debug(f"Token {mint[:8]}... transitioned to COLD")

    async def is_hot(self, mint: str) -> bool:
        """Check if token is currently HOT."""
        return await self.get_state(mint) == TokenState.HOT

    async def is_warm_or_hot(self, mint: str) -> bool:
        """Check if token is WARM or HOT (should store swaps)."""
        state = await self.get_state(mint)
        return state in (TokenState.WARM, TokenState.HOT)

    async def get_hot_tokens(self) -> Set[str]:
        """Get all currently HOT tokens."""
        return await self.redis.get_hot_tokens()

    def on_hot(self, callback: Callable):
        """Register callback for HOT transitions."""
        self._hot_callbacks.append(callback)

    async def process_backfill_queue(self, processor: Callable):
        """Process backfill queue for newly HOT tokens."""
        while True:
            try:
                mint = await self._backfill_queue.get()
                await self._backfill_token(mint, processor)
                self._backfill_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Backfill error: {e}")

    async def _backfill_token(self, mint: str, processor: Callable):
        """Backfill swap events from delta log for a token."""
        logger.info(f"Starting backfill for {mint[:8]}...")

        # Read recent delta records for this mint
        records = await self.delta_log.read_for_mint(mint)

        processed = 0
        for record in records:
            try:
                await processor(record)
                processed += 1
            except Exception as e:
                logger.error(f"Backfill record error: {e}")

        logger.info(f"Backfill complete for {mint[:8]}: {processed} records")

    async def refresh_hot_tokens(self):
        """Refresh HOT token TTLs and cleanup expired."""
        hot_tokens = await self.redis.get_hot_tokens()

        for mint in list(hot_tokens):
            if not await self.redis.is_token_hot(mint):
                # Token expired
                await self.transition_to_cold(mint)
                self._state_cache.pop(mint, None)

    async def start_maintenance_loop(self, interval_seconds: int = 60):
        """Start periodic maintenance loop."""
        while True:
            try:
                await asyncio.sleep(interval_seconds)
                await self.refresh_hot_tokens()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Maintenance loop error: {e}")

    def get_stats(self) -> dict:
        """Get state manager statistics."""
        state_counts = {}
        for state in list(self._state_cache.values()):
            state_counts[state.value] = state_counts.get(state.value, 0) + 1

        return {
            "cached_tokens": len(self._state_cache),
            "state_counts": state_counts,
            "backfill_queue_size": self._backfill_queue.qsize(),
        }
