"""Simple TTL cache for reducing Redis round-trips."""

import time
from typing import Any, Dict, Optional, TypeVar, Generic

T = TypeVar('T')


class TTLCache(Generic[T]):
    """
    In-memory TTL cache for reducing Redis round-trips.

    Thread-safe for asyncio (single-threaded event loop).
    """

    def __init__(self, ttl: float = 3.0, max_size: int = 10000):
        self.ttl = ttl
        self.max_size = max_size
        self._data: Dict[str, tuple[T, float]] = {}  # key -> (value, expires_at)
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[T]:
        """Get value if exists and not expired."""
        item = self._data.get(key)
        if item is None:
            self._misses += 1
            return None

        value, expires_at = item
        if expires_at < time.time():
            del self._data[key]
            self._misses += 1
            return None

        self._hits += 1
        return value

    def set(self, key: str, value: T, ttl: Optional[float] = None):
        """Set value with optional custom TTL."""
        # Evict if at max size
        if len(self._data) >= self.max_size:
            self._evict_expired()

        actual_ttl = ttl if ttl is not None else self.ttl
        self._data[key] = (value, time.time() + actual_ttl)

    def delete(self, key: str):
        """Delete a key."""
        self._data.pop(key, None)

    def contains(self, key: str) -> bool:
        """Check if key exists and is not expired."""
        return self.get(key) is not None

    def set_many(self, items: Dict[str, T], ttl: Optional[float] = None):
        """Set multiple values at once."""
        actual_ttl = ttl if ttl is not None else self.ttl
        expires_at = time.time() + actual_ttl
        for key, value in items.items():
            self._data[key] = (value, expires_at)

    def get_many(self, keys: list) -> Dict[str, T]:
        """Get multiple values, returns dict of found keys."""
        result = {}
        now = time.time()
        for key in keys:
            item = self._data.get(key)
            if item:
                value, expires_at = item
                if expires_at >= now:
                    result[key] = value
                    self._hits += 1
                else:
                    del self._data[key]
                    self._misses += 1
            else:
                self._misses += 1
        return result

    def _evict_expired(self):
        """Remove expired entries."""
        now = time.time()
        to_delete = [k for k, (_, exp) in self._data.items() if exp < now]
        for k in to_delete:
            del self._data[k]

        # If still too big, evict oldest
        if len(self._data) >= self.max_size:
            sorted_keys = sorted(self._data.keys(), key=lambda k: self._data[k][1])
            for k in sorted_keys[:len(self._data) // 4]:
                del self._data[k]

    def clear(self):
        """Clear all entries."""
        self._data.clear()

    def stats(self) -> dict:
        """Get cache statistics."""
        hit_rate = self._hits / (self._hits + self._misses) if (self._hits + self._misses) > 0 else 0
        return {
            "size": len(self._data),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": hit_rate,
            "ttl": self.ttl,
        }


class HotTokenCache:
    """
    Specialized cache for HOT token set with refresh.

    Caches the set of HOT tokens locally, refreshing periodically.
    """

    def __init__(self, ttl: float = 5.0):
        self.ttl = ttl
        self._tokens: set = set()
        self._last_refresh: float = 0
        self._pending_refresh: bool = False

    def is_hot(self, mint: str) -> Optional[bool]:
        """
        Check if token is HOT.

        Returns:
            True/False if cache is fresh, None if needs refresh.
        """
        if time.time() - self._last_refresh > self.ttl:
            return None  # Cache stale, need refresh
        return mint in self._tokens

    def update(self, hot_tokens: set):
        """Update the hot token set."""
        self._tokens = hot_tokens
        self._last_refresh = time.time()

    def add(self, mint: str):
        """Add a token to the HOT set (local only)."""
        self._tokens.add(mint)

    def needs_refresh(self) -> bool:
        """Check if cache needs refresh."""
        return time.time() - self._last_refresh > self.ttl

    def get_all(self) -> set:
        """Get all cached HOT tokens."""
        return self._tokens.copy()
