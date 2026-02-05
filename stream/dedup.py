"""Deduplication filter using Redis SET NX EX."""

import logging
from typing import Optional

from core.ttl_cache import TTLCache
from storage.redis_client import RedisClient
from config.settings import settings

logger = logging.getLogger(__name__)


class DedupFilter:
    """
    Signature deduplication using Redis SET NX EX.

    Simple, automatic expiry-based dedup that doesn't require cleanup.
    """

    def __init__(
        self,
        redis_client: RedisClient,
        ttl_seconds: Optional[int] = None,
    ):
        self.redis = redis_client
        self.ttl = ttl_seconds or settings.dedup_ttl_seconds
        self._local_cache: TTLCache[bool] = TTLCache(ttl=float(self.ttl), max_size=100000)

        # Stats
        self._checked = 0
        self._duplicates = 0

    async def is_duplicate(self, signature: str) -> bool:
        """
        Check if signature already processed.

        Uses SET NX EX for atomic check-and-set with auto-expiry.

        Returns:
            True if duplicate (already seen), False if new
        """
        cache_key = f"sig:{signature}"
        if self._local_cache.contains(cache_key):
            self._checked += 1
            self._duplicates += 1
            return True

        self._checked += 1

        result = await self.redis.redis.set(
            cache_key,
            b"1",
            ex=self.ttl,
            nx=True
        )

        if result is None:
            # Key already existed = duplicate
            self._duplicates += 1
            self._local_cache.set(cache_key, True)
            return True

        self._local_cache.set(cache_key, True)
        return False

    async def check_batch(self, signatures: list) -> list:
        """
        Check multiple signatures, return list of non-duplicates.

        More efficient than individual checks for batch processing.
        """
        non_duplicates = []
        to_check = []

        for sig in signatures:
            cache_key = f"sig:{sig}"
            if self._local_cache.contains(cache_key):
                self._checked += 1
                self._duplicates += 1
                continue
            to_check.append(sig)

        if not to_check:
            return non_duplicates

        # Use pipeline for efficiency
        pipe = self.redis.redis.pipeline()
        for sig in to_check:
            pipe.set(f"sig:{sig}", b"1", ex=self.ttl, nx=True)

        results = await pipe.execute()

        for sig, result in zip(to_check, results):
            self._checked += 1
            cache_key = f"sig:{sig}"
            if result is None:
                self._duplicates += 1
                self._local_cache.set(cache_key, True)
            else:
                self._local_cache.set(cache_key, True)
                non_duplicates.append(sig)

        return non_duplicates

    def get_stats(self) -> dict:
        """Get dedup statistics."""
        dup_rate = (self._duplicates / self._checked * 100) if self._checked > 0 else 0

        return {
            "checked": self._checked,
            "duplicates": self._duplicates,
            "duplicate_rate_pct": dup_rate,
            "ttl_seconds": self.ttl,
        }

    def reset_stats(self):
        """Reset statistics counters."""
        self._checked = 0
        self._duplicates = 0
