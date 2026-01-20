"""Rolling counter management for token activity tracking."""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from storage.redis_client import RedisClient

logger = logging.getLogger(__name__)


@dataclass
class TokenStats:
    """Token activity statistics for a time window."""
    mint: str
    window_seconds: int

    # Counts
    buy_count: int = 0
    sell_count: int = 0
    unique_buyers: int = 0
    unique_sellers: int = 0

    # Volume
    volume_sol: float = 0.0
    avg_buy_size: float = 0.0

    # Ratios
    buy_sell_ratio: float = 0.0

    # Concentration
    top_buyers_volume: List[Tuple[str, float]] = None
    top_3_volume_share: float = 0.0

    # New wallet detection
    new_wallet_count: int = 0
    new_wallet_pct: float = 0.0

    def __post_init__(self):
        if self.top_buyers_volume is None:
            self.top_buyers_volume = []


class CounterManager:
    """
    Manages rolling counters for token activity tracking.

    Uses Redis bucketed counters to efficiently track:
    - Buy/sell counts per time window
    - Unique buyers/sellers (HyperLogLog)
    - Volume per time window
    - Per-wallet volumes for concentration analysis
    """

    def __init__(self, redis_client: RedisClient):
        self.redis = redis_client
        self._active_mints: Set[str] = set()
        self._stats_cache: Dict[str, TokenStats] = {}
        self._cache_ttl = 1.0  # Cache stats for 1 second
        self._last_cache_time: Dict[str, float] = {}

    async def record_swap(
        self,
        mint: str,
        user_wallet: str,
        quote_amount_sol: float,
        side: str = "buy"
    ):
        """Record a swap event in the rolling counters."""
        self._active_mints.add(mint)

        await self.redis.increment_counters(
            mint=mint,
            user_wallet=user_wallet,
            quote_amount_sol=quote_amount_sol,
            side=side,
        )

        # Invalidate cache for this mint
        if mint in self._last_cache_time:
            del self._last_cache_time[mint]

    async def get_stats(
        self,
        mint: str,
        window_seconds: int = 300
    ) -> TokenStats:
        """
        Get token statistics for a time window.

        Uses caching to reduce Redis queries.
        """
        cache_key = f"{mint}:{window_seconds}"
        now = time.time()

        # Check cache
        if cache_key in self._stats_cache:
            if now - self._last_cache_time.get(cache_key, 0) < self._cache_ttl:
                return self._stats_cache[cache_key]

        # Fetch from Redis
        raw_stats = await self.redis.get_rolling_stats(mint, window_seconds)

        # Get top buyers for concentration
        top_buyers = await self.redis.get_top_buyers_volume(
            mint, window_seconds, top_n=3
        )

        # Calculate top 3 volume share
        total_volume = raw_stats.get("volume_sol", 0)
        top_3_volume = sum(vol for _, vol in top_buyers[:3])
        top_3_share = top_3_volume / total_volume if total_volume > 0 else 0

        # Calculate new wallet percentage
        new_wallet_count = await self._count_new_wallets(mint, window_seconds)
        unique_buyers = raw_stats.get("unique_buyers", 0)
        new_wallet_pct = new_wallet_count / unique_buyers if unique_buyers > 0 else 0

        stats = TokenStats(
            mint=mint,
            window_seconds=window_seconds,
            buy_count=raw_stats.get("buy_count", 0),
            sell_count=raw_stats.get("sell_count", 0),
            unique_buyers=raw_stats.get("unique_buyers", 0),
            unique_sellers=raw_stats.get("unique_sellers", 0),
            volume_sol=raw_stats.get("volume_sol", 0),
            avg_buy_size=raw_stats.get("avg_buy_size", 0),
            buy_sell_ratio=raw_stats.get("buy_sell_ratio", 0),
            top_buyers_volume=top_buyers,
            top_3_volume_share=top_3_share,
            new_wallet_count=new_wallet_count,
            new_wallet_pct=new_wallet_pct,
        )

        # Update cache
        self._stats_cache[cache_key] = stats
        self._last_cache_time[cache_key] = now

        return stats

    async def _count_new_wallets(
        self,
        mint: str,
        window_seconds: int
    ) -> int:
        """Count wallets first seen within the window."""
        # This is expensive - simplified implementation
        # In production, track new wallets per bucket

        top_buyers = await self.redis.get_top_buyers_volume(
            mint, window_seconds, top_n=100
        )

        now = int(time.time())
        new_count = 0

        for wallet, _ in top_buyers:
            first_seen = await self.redis.get_wallet_first_seen(wallet)
            if first_seen and (now - first_seen) <= window_seconds:
                new_count += 1

        return new_count

    async def get_active_mints(self) -> Set[str]:
        """Get mints with recent activity."""
        return self._active_mints.copy()

    async def get_all_stats_5m(self) -> Dict[str, TokenStats]:
        """Get 5-minute stats for all active mints."""
        results = {}

        for mint in list(self._active_mints):
            try:
                stats = await self.get_stats(mint, 300)
                results[mint] = stats
            except Exception as e:
                logger.error(f"Failed to get stats for {mint}: {e}")

        return results

    async def cleanup_inactive(self, max_age_seconds: int = 3600):
        """Remove mints without recent activity from tracking."""
        # Get mints with zero recent activity
        inactive = []

        for mint in list(self._active_mints):
            stats = await self.get_stats(mint, max_age_seconds)
            if stats.buy_count == 0 and stats.sell_count == 0:
                inactive.append(mint)

        for mint in inactive:
            self._active_mints.discard(mint)
            # Clear cache
            for key in list(self._stats_cache.keys()):
                if key.startswith(mint):
                    del self._stats_cache[key]

        if inactive:
            logger.info(f"Cleaned up {len(inactive)} inactive mints")

    def get_manager_stats(self) -> dict:
        """Get counter manager statistics."""
        return {
            "active_mints": len(self._active_mints),
            "cache_size": len(self._stats_cache),
        }
