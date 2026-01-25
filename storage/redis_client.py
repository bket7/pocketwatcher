"""Redis client for streams, dedup, and counters."""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import redis.asyncio as redis
from redis.asyncio import Redis

from config.settings import settings

logger = logging.getLogger(__name__)

# Stream names
TX_STREAM = "stream:tx"
CONSUMER_GROUP = "parsers"


class RedisClient:
    """Redis client wrapper for Pocketwatcher operations."""

    def __init__(self, url: Optional[str] = None):
        self.url = url or settings.redis_url
        self._redis: Optional[Redis] = None
        self._pubsub = None

    async def connect(self) -> Redis:
        """Connect to Redis."""
        if self._redis is None:
            self._redis = redis.from_url(
                self.url,
                encoding="utf-8",
                decode_responses=False,  # We handle binary data
            )
            # Ensure consumer group exists
            try:
                await self._redis.xgroup_create(
                    TX_STREAM,
                    CONSUMER_GROUP,
                    id="0",
                    mkstream=True
                )
                logger.info(f"Created consumer group {CONSUMER_GROUP}")
            except redis.ResponseError as e:
                if "BUSYGROUP" not in str(e):
                    raise
                logger.debug(f"Consumer group {CONSUMER_GROUP} already exists")
        return self._redis

    async def close(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None

    @property
    def redis(self) -> Redis:
        """Get Redis connection (must be connected first)."""
        if self._redis is None:
            raise RuntimeError("Not connected to Redis")
        return self._redis

    # ============== Stream Operations ==============

    async def push_to_stream(self, raw_tx: bytes) -> str:
        """Push raw transaction to ingest stream."""
        msg_id = await self.redis.xadd(
            TX_STREAM,
            {"data": raw_tx},
            maxlen=settings.redis_stream_maxlen,
            approximate=True
        )
        return msg_id

    async def read_from_stream(
        self,
        consumer_name: str,
        count: int = 100,
        block_ms: int = 1000
    ) -> List[Tuple[bytes, bytes, Dict[bytes, bytes]]]:
        """
        Read messages from stream using consumer group.

        Returns list of (stream_name, message_id, {field: value})
        """
        messages = await self.redis.xreadgroup(
            groupname=CONSUMER_GROUP,
            consumername=consumer_name,
            streams={TX_STREAM: ">"},
            count=count,
            block=block_ms
        )
        return messages or []

    async def ack_messages(self, message_ids: List[bytes]):
        """Acknowledge processed messages."""
        if message_ids:
            await self.redis.xack(TX_STREAM, CONSUMER_GROUP, *message_ids)

    async def get_stream_length(self) -> int:
        """Get current stream length."""
        return await self.redis.xlen(TX_STREAM)

    async def get_stream_info(self) -> Dict[str, Any]:
        """Get stream info including lag."""
        try:
            info = await self.redis.xinfo_stream(TX_STREAM)
            return {
                "length": info.get("length", 0),
                "first_entry": info.get("first-entry"),
                "last_entry": info.get("last-entry"),
            }
        except redis.ResponseError:
            return {"length": 0}

    # ============== Dedup Operations ==============

    async def is_duplicate(self, signature: str) -> bool:
        """Check if signature already processed. Returns True if duplicate."""
        result = await self.redis.set(
            f"sig:{signature}",
            b"1",
            ex=settings.dedup_ttl_seconds,
            nx=True
        )
        return result is None  # None means key existed = duplicate

    # ============== Rolling Counter Operations ==============

    def _get_bucket_key(
        self,
        mint: str,
        metric: str,
        bucket_seconds: int = 60
    ) -> str:
        """Generate bucket key based on current time."""
        bucket = int(time.time()) // bucket_seconds
        return f"{metric}:{bucket_seconds}s:{bucket}:{mint}"

    async def increment_counters(
        self,
        mint: str,
        user_wallet: str,
        quote_amount_sol: float,
        side: str = "buy"
    ):
        """Increment rolling counters for a swap."""
        pipe = self.redis.pipeline()

        is_buy = side == "buy"
        metric_prefix = "buys" if is_buy else "sells"
        buyer_prefix = "buyers" if is_buy else "sellers"

        # --- 5-minute windows (for fast stealth detection) ---
        bucket_5m = self._get_bucket_key(mint, metric_prefix, 300)
        pipe.incr(bucket_5m)
        pipe.expire(bucket_5m, 900)  # Keep 3 buckets (15 min)

        hll_5m = self._get_bucket_key(mint, buyer_prefix, 300)
        pipe.pfadd(hll_5m, user_wallet)
        pipe.expire(hll_5m, 900)

        vol_5m = self._get_bucket_key(mint, "volume", 300)
        pipe.incrbyfloat(vol_5m, quote_amount_sol)
        pipe.expire(vol_5m, 900)

        # Track individual buy sizes for avg calculation
        if is_buy:
            sizes_5m = self._get_bucket_key(mint, "buy_sizes", 300)
            pipe.rpush(sizes_5m, str(quote_amount_sol))
            pipe.expire(sizes_5m, 900)

        # --- 1-hour windows (for slow stealth detection) ---
        bucket_1h = self._get_bucket_key(mint, metric_prefix, 3600)
        pipe.incr(bucket_1h)
        pipe.expire(bucket_1h, 7200)  # Keep 2 buckets (2 hours)

        hll_1h = self._get_bucket_key(mint, buyer_prefix, 3600)
        pipe.pfadd(hll_1h, user_wallet)
        pipe.expire(hll_1h, 7200)

        vol_1h = self._get_bucket_key(mint, "volume", 3600)
        pipe.incrbyfloat(vol_1h, quote_amount_sol)
        pipe.expire(vol_1h, 7200)

        if is_buy:
            sizes_1h = self._get_bucket_key(mint, "buy_sizes", 3600)
            pipe.rpush(sizes_1h, str(quote_amount_sol))
            pipe.expire(sizes_1h, 7200)

        # Track wallet first-seen (for "new wallet" detection)
        wallet_key = f"wallet:first_seen:{user_wallet}"
        pipe.setnx(wallet_key, int(time.time()))
        pipe.expire(wallet_key, 86400 * 7)  # Keep 7 days

        # Track per-wallet volume for concentration analysis
        wallet_vol_5m = self._get_bucket_key(f"{mint}:{user_wallet}", "wallet_vol", 300)
        pipe.incrbyfloat(wallet_vol_5m, quote_amount_sol)
        pipe.expire(wallet_vol_5m, 900)

        await pipe.execute()

    async def get_rolling_stats(
        self,
        mint: str,
        window_seconds: int = 300
    ) -> Dict[str, Any]:
        """Get rolling stats for a mint across recent buckets."""
        bucket_size = 60 if window_seconds <= 120 else 300
        num_buckets = max(1, window_seconds // bucket_size)
        current_bucket = int(time.time()) // bucket_size

        pipe = self.redis.pipeline()

        # Collect keys for all buckets
        buy_keys = []
        sell_keys = []
        vol_keys = []
        buyer_keys = []
        seller_keys = []
        sizes_keys = []

        for i in range(num_buckets):
            bucket = current_bucket - i
            buy_keys.append(f"buys:{bucket_size}s:{bucket}:{mint}")
            sell_keys.append(f"sells:{bucket_size}s:{bucket}:{mint}")
            vol_keys.append(f"volume:{bucket_size}s:{bucket}:{mint}")
            buyer_keys.append(f"buyers:{bucket_size}s:{bucket}:{mint}")
            seller_keys.append(f"sellers:{bucket_size}s:{bucket}:{mint}")
            sizes_keys.append(f"buy_sizes:{bucket_size}s:{bucket}:{mint}")

        # Queue up all gets
        for key in buy_keys:
            pipe.get(key)
        for key in sell_keys:
            pipe.get(key)
        for key in vol_keys:
            pipe.get(key)

        results = await pipe.execute()

        # Parse results
        n = len(buy_keys)
        buy_counts = [int(r or 0) for r in results[:n]]
        sell_counts = [int(r or 0) for r in results[n:2*n]]
        volumes = [float(r or 0) for r in results[2*n:3*n]]

        total_buys = sum(buy_counts)
        total_sells = sum(sell_counts)
        total_volume = sum(volumes)

        # Get HyperLogLog counts for unique buyers/sellers
        pipe2 = self.redis.pipeline()
        for key in buyer_keys:
            pipe2.pfcount(key)
        for key in seller_keys:
            pipe2.pfcount(key)
        hll_results = await pipe2.execute()

        unique_buyers = max(hll_results[:n]) if hll_results[:n] else 0
        unique_sellers = max(hll_results[n:]) if hll_results[n:] else 0

        # Calculate buy/sell ratio
        buy_sell_ratio = total_buys / total_sells if total_sells > 0 else float('inf')

        # Average buy size
        avg_buy_size = total_volume / total_buys if total_buys > 0 else 0

        return {
            "buy_count": total_buys,
            "sell_count": total_sells,
            "volume_sol": total_volume,
            "unique_buyers": unique_buyers,
            "unique_sellers": unique_sellers,
            "buy_sell_ratio": buy_sell_ratio,
            "avg_buy_size": avg_buy_size,
        }

    async def get_wallet_first_seen(self, wallet: str) -> Optional[int]:
        """Get wallet first seen timestamp."""
        result = await self.redis.get(f"wallet:first_seen:{wallet}")
        return int(result) if result else None

    async def get_top_buyers_volume(
        self,
        mint: str,
        window_seconds: int = 300,
        top_n: int = 3
    ) -> List[Tuple[str, float]]:
        """Get top N buyers by volume for concentration analysis."""
        bucket_size = 300
        current_bucket = int(time.time()) // bucket_size

        # Scan for wallet volumes (this is expensive, consider alternatives)
        pattern = f"wallet_vol:{bucket_size}s:{current_bucket}:{mint}:*"
        wallet_volumes = []

        async for key in self.redis.scan_iter(match=pattern):
            key_str = key.decode() if isinstance(key, bytes) else key
            wallet = key_str.split(":")[-1]
            vol = await self.redis.get(key)
            if vol:
                wallet_volumes.append((wallet, float(vol)))

        # Sort by volume descending
        wallet_volumes.sort(key=lambda x: x[1], reverse=True)
        return wallet_volumes[:top_n]

    # ============== Hot Token Management ==============

    async def mark_token_hot(self, mint: str, ttl_seconds: int = 3600):
        """Mark a token as HOT with expiry."""
        await self.redis.set(f"hot:{mint}", b"1", ex=ttl_seconds)
        await self.redis.sadd("hot_tokens", mint)

    async def is_token_hot(self, mint: str) -> bool:
        """Check if token is currently HOT."""
        return await self.redis.exists(f"hot:{mint}") > 0

    async def get_hot_tokens(self) -> Set[str]:
        """Get all currently HOT tokens."""
        members = await self.redis.smembers("hot_tokens")
        # Clean up expired ones
        hot = set()
        for m in members:
            mint = m.decode() if isinstance(m, bytes) else m
            if await self.is_token_hot(mint):
                hot.add(mint)
            else:
                await self.redis.srem("hot_tokens", mint)
        return hot

    # ============== Token Market Cap Tracking ==============

    async def set_token_mcap(self, mint: str, mcap_sol: float, price_sol: float, ttl_seconds: int = 3600):
        """Store latest market cap and price for a token."""
        pipe = self.redis.pipeline()
        pipe.set(f"mcap:{mint}", str(mcap_sol), ex=ttl_seconds)
        pipe.set(f"price:{mint}", str(price_sol), ex=ttl_seconds)
        await pipe.execute()

    async def get_token_mcap(self, mint: str) -> Optional[Dict[str, float]]:
        """Get latest market cap and price for a token."""
        pipe = self.redis.pipeline()
        pipe.get(f"mcap:{mint}")
        pipe.get(f"price:{mint}")
        results = await pipe.execute()

        mcap = results[0]
        price = results[1]

        if mcap is not None:
            return {
                "mcap_sol": float(mcap),
                "price_sol": float(price) if price else None,
            }
        return None

    # ============== Config Hot Reload ==============

    async def get_config(self, key: str) -> Optional[bytes]:
        """Get config from Redis."""
        return await self.redis.get(f"cfg:{key}")

    async def set_config(self, key: str, value: bytes):
        """Set config in Redis and notify subscribers."""
        await self.redis.set(f"cfg:{key}", value)
        await self.redis.publish("cfg:reload", key)

    async def subscribe_config_reload(self, callback):
        """Subscribe to config reload notifications."""
        self._pubsub = self.redis.pubsub()
        await self._pubsub.subscribe("cfg:reload")

        async def listener():
            async for message in self._pubsub.listen():
                if message["type"] == "message":
                    await callback(message["data"])

        return asyncio.create_task(listener())

    # ============== Unknown Program Discovery ==============

    async def track_program(self, program_id: str, slot: int, cooccurs_with: Set[str]):
        """Track unknown program occurrence."""
        pipe = self.redis.pipeline()

        # Increment count
        pipe.incr(f"prog:count:{program_id}")

        # Set first seen if not exists
        pipe.setnx(f"prog:first:{program_id}", slot)

        # Track co-occurrences
        for known_prog in cooccurs_with:
            pipe.sadd(f"prog:cooccurs:{program_id}", known_prog)

        # Set expiry on all keys (7 days)
        pipe.expire(f"prog:count:{program_id}", 604800)
        pipe.expire(f"prog:first:{program_id}", 604800)
        pipe.expire(f"prog:cooccurs:{program_id}", 604800)

        await pipe.execute()

    async def get_program_stats(self, program_id: str) -> Dict[str, Any]:
        """Get program occurrence stats."""
        pipe = self.redis.pipeline()
        pipe.get(f"prog:count:{program_id}")
        pipe.get(f"prog:first:{program_id}")
        pipe.smembers(f"prog:cooccurs:{program_id}")
        results = await pipe.execute()

        return {
            "count": int(results[0] or 0),
            "first_seen_slot": int(results[1]) if results[1] else None,
            "cooccurs_with": {m.decode() if isinstance(m, bytes) else m for m in (results[2] or set())},
        }

    # ============== Backtest Cache Operations ==============

    async def get_backtest_cache(self, hours: int) -> Optional[bytes]:
        """Get cached backtest results for given time period."""
        return await self.redis.get(f"backtest:cache:{hours}h")

    async def set_backtest_cache(self, hours: int, data: bytes, ttl_seconds: int = 300):
        """Cache backtest results."""
        await self.redis.set(f"backtest:cache:{hours}h", data, ex=ttl_seconds)

    async def get_backtest_timestamp(self, hours: int) -> Optional[int]:
        """Get timestamp when backtest cache was last updated."""
        result = await self.redis.get(f"backtest:timestamp:{hours}h")
        return int(result) if result else None

    async def set_backtest_timestamp(self, hours: int, timestamp: int, ttl_seconds: int = 300):
        """Set backtest cache timestamp."""
        await self.redis.set(f"backtest:timestamp:{hours}h", str(timestamp), ex=ttl_seconds)

    async def get_token_price_cache(self, mint: str) -> Optional[bytes]:
        """Get cached token price data."""
        return await self.redis.get(f"price:cache:{mint}")

    async def set_token_price_cache(self, mint: str, data: bytes, ttl_seconds: int = 3600):
        """Cache token price data (1 hour default)."""
        await self.redis.set(f"price:cache:{mint}", data, ex=ttl_seconds)
