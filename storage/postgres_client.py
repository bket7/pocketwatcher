"""PostgreSQL client for persistent storage."""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import asyncpg
from asyncpg import Pool

from config.settings import settings
from models.events import SwapEventFull, SwapSide
from models.profiles import Alert, TokenProfile, TokenState, WalletProfile

logger = logging.getLogger(__name__)


class PostgresClient:
    """PostgreSQL client for Pocketwatcher persistent storage."""

    def __init__(self, url: Optional[str] = None):
        self.url = url or settings.postgres_url
        self._pool: Optional[Pool] = None

    async def connect(self) -> Pool:
        """Connect to PostgreSQL and create tables if needed."""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self.url, min_size=2, max_size=10)
            await self._create_tables()
            logger.info("Connected to PostgreSQL")
        return self._pool

    async def close(self):
        """Close PostgreSQL connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> Pool:
        """Get connection pool (must be connected first)."""
        if self._pool is None:
            raise RuntimeError("Not connected to PostgreSQL")
        return self._pool

    async def _create_tables(self):
        """Create database tables if they don't exist."""
        async with self.pool.acquire() as conn:
            # Token profiles table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS token_profiles (
                    mint TEXT PRIMARY KEY,
                    state TEXT NOT NULL DEFAULT 'cold',
                    first_seen TIMESTAMPTZ,
                    last_seen TIMESTAMPTZ,
                    became_hot_at TIMESTAMPTZ,
                    total_buys INTEGER DEFAULT 0,
                    total_sells INTEGER DEFAULT 0,
                    total_volume_sol DOUBLE PRECISION DEFAULT 0,
                    unique_buyers INTEGER DEFAULT 0,
                    unique_sellers INTEGER DEFAULT 0,
                    trigger_reason TEXT,
                    name TEXT,
                    symbol TEXT,
                    decimals INTEGER DEFAULT 9,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            # Swap events table (for HOT/WARM tokens only)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS swap_events (
                    id SERIAL PRIMARY KEY,
                    signature TEXT NOT NULL,
                    slot BIGINT NOT NULL,
                    block_time BIGINT NOT NULL,
                    venue TEXT NOT NULL,
                    user_wallet TEXT NOT NULL,
                    side TEXT NOT NULL,
                    base_mint TEXT NOT NULL,
                    base_amount BIGINT NOT NULL,
                    quote_mint TEXT NOT NULL,
                    quote_amount BIGINT NOT NULL,
                    confidence DOUBLE PRECISION NOT NULL,
                    route_depth INTEGER DEFAULT 1,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(signature, base_mint)
                )
            """)

            # Index for efficient queries
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_swap_events_base_mint
                ON swap_events(base_mint, block_time DESC)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_swap_events_user_wallet
                ON swap_events(user_wallet, block_time DESC)
            """)

            # Wallet profiles table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS wallet_profiles (
                    address TEXT PRIMARY KEY,
                    first_seen TIMESTAMPTZ,
                    last_seen TIMESTAMPTZ,
                    total_buys INTEGER DEFAULT 0,
                    total_sells INTEGER DEFAULT 0,
                    total_volume_sol DOUBLE PRECISION DEFAULT 0,
                    tokens_traded TEXT[] DEFAULT '{}',
                    cluster_id TEXT,
                    cluster_size INTEGER DEFAULT 1,
                    funded_by TEXT,
                    funding_amount_sol DOUBLE PRECISION,
                    funding_hop INTEGER DEFAULT 0,
                    is_new_wallet BOOLEAN DEFAULT FALSE,
                    cto_score DOUBLE PRECISION DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            # Alerts table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id SERIAL PRIMARY KEY,
                    mint TEXT NOT NULL,
                    token_name TEXT,
                    token_symbol TEXT,
                    trigger_name TEXT NOT NULL,
                    trigger_reason TEXT NOT NULL,
                    buy_count_5m INTEGER DEFAULT 0,
                    unique_buyers_5m INTEGER DEFAULT 0,
                    volume_sol_5m DOUBLE PRECISION DEFAULT 0,
                    buy_sell_ratio_5m DOUBLE PRECISION DEFAULT 0,
                    top_buyers JSONB DEFAULT '[]',
                    cluster_summary TEXT,
                    enrichment_degraded BOOLEAN DEFAULT FALSE,
                    discord_sent BOOLEAN DEFAULT FALSE,
                    telegram_sent BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_alerts_mint
                ON alerts(mint, created_at DESC)
            """)

            # Add price/mcap columns to alerts table (migration)
            await conn.execute("""
                ALTER TABLE alerts ADD COLUMN IF NOT EXISTS price_sol DOUBLE PRECISION;
            """)
            await conn.execute("""
                ALTER TABLE alerts ADD COLUMN IF NOT EXISTS mcap_sol DOUBLE PRECISION;
            """)
            await conn.execute("""
                ALTER TABLE alerts ADD COLUMN IF NOT EXISTS token_supply BIGINT;
            """)

            logger.info("Database tables created/verified")

    # ============== Token Profile Operations ==============

    async def get_token_profile(self, mint: str) -> Optional[TokenProfile]:
        """Get token profile by mint address."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM token_profiles WHERE mint = $1",
                mint
            )
            if row:
                return TokenProfile(
                    mint=row["mint"],
                    state=TokenState(row["state"]),
                    first_seen=row["first_seen"],
                    last_seen=row["last_seen"],
                    became_hot_at=row["became_hot_at"],
                    total_buys=row["total_buys"],
                    total_sells=row["total_sells"],
                    total_volume_sol=row["total_volume_sol"],
                    unique_buyers=row["unique_buyers"],
                    unique_sellers=row["unique_sellers"],
                    trigger_reason=row["trigger_reason"],
                    name=row["name"],
                    symbol=row["symbol"],
                    decimals=row["decimals"],
                )
            return None

    async def upsert_token_profile(self, profile: TokenProfile):
        """Insert or update token profile."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO token_profiles (
                    mint, state, first_seen, last_seen, became_hot_at,
                    total_buys, total_sells, total_volume_sol,
                    unique_buyers, unique_sellers, trigger_reason,
                    name, symbol, decimals, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, NOW())
                ON CONFLICT (mint) DO UPDATE SET
                    state = EXCLUDED.state,
                    last_seen = EXCLUDED.last_seen,
                    became_hot_at = COALESCE(EXCLUDED.became_hot_at, token_profiles.became_hot_at),
                    total_buys = EXCLUDED.total_buys,
                    total_sells = EXCLUDED.total_sells,
                    total_volume_sol = EXCLUDED.total_volume_sol,
                    unique_buyers = EXCLUDED.unique_buyers,
                    unique_sellers = EXCLUDED.unique_sellers,
                    trigger_reason = COALESCE(EXCLUDED.trigger_reason, token_profiles.trigger_reason),
                    name = COALESCE(EXCLUDED.name, token_profiles.name),
                    symbol = COALESCE(EXCLUDED.symbol, token_profiles.symbol),
                    decimals = EXCLUDED.decimals,
                    updated_at = NOW()
            """,
                profile.mint,
                profile.state.value,
                profile.first_seen,
                profile.last_seen,
                profile.became_hot_at,
                profile.total_buys,
                profile.total_sells,
                profile.total_volume_sol,
                profile.unique_buyers,
                profile.unique_sellers,
                profile.trigger_reason,
                profile.name,
                profile.symbol,
                profile.decimals,
            )

    async def update_token_state(self, mint: str, state: TokenState, reason: Optional[str] = None):
        """Update token state."""
        async with self.pool.acquire() as conn:
            if state == TokenState.HOT:
                await conn.execute("""
                    UPDATE token_profiles
                    SET state = $2, became_hot_at = NOW(), trigger_reason = $3, updated_at = NOW()
                    WHERE mint = $1
                """, mint, state.value, reason)
            else:
                await conn.execute("""
                    UPDATE token_profiles
                    SET state = $2, updated_at = NOW()
                    WHERE mint = $1
                """, mint, state.value)

    # ============== Swap Event Operations ==============

    async def insert_swap_event(self, event: SwapEventFull):
        """Insert a swap event."""
        async with self.pool.acquire() as conn:
            try:
                await conn.execute("""
                    INSERT INTO swap_events (
                        signature, slot, block_time, venue, user_wallet,
                        side, base_mint, base_amount, quote_mint, quote_amount,
                        confidence, route_depth
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    ON CONFLICT (signature, base_mint) DO NOTHING
                """,
                    event.signature,
                    event.slot,
                    event.block_time,
                    event.venue,
                    event.user_wallet,
                    event.side.value if isinstance(event.side, SwapSide) else event.side,
                    event.base_mint,
                    event.base_amount,
                    event.quote_mint,
                    event.quote_amount,
                    event.confidence,
                    event.route_depth,
                )
            except Exception as e:
                logger.error(f"Failed to insert swap event: {e}")

    async def get_recent_swaps(
        self,
        mint: str,
        limit: int = 100,
        since_block_time: Optional[int] = None
    ) -> List[SwapEventFull]:
        """Get recent swaps for a token."""
        async with self.pool.acquire() as conn:
            if since_block_time:
                rows = await conn.fetch("""
                    SELECT * FROM swap_events
                    WHERE base_mint = $1 AND block_time >= $2
                    ORDER BY block_time DESC
                    LIMIT $3
                """, mint, since_block_time, limit)
            else:
                rows = await conn.fetch("""
                    SELECT * FROM swap_events
                    WHERE base_mint = $1
                    ORDER BY block_time DESC
                    LIMIT $2
                """, mint, limit)

            return [
                SwapEventFull(
                    signature=row["signature"],
                    slot=row["slot"],
                    block_time=row["block_time"],
                    venue=row["venue"],
                    user_wallet=row["user_wallet"],
                    side=SwapSide(row["side"]),
                    base_mint=row["base_mint"],
                    base_amount=row["base_amount"],
                    quote_mint=row["quote_mint"],
                    quote_amount=row["quote_amount"],
                    confidence=row["confidence"],
                    route_depth=row["route_depth"],
                )
                for row in rows
            ]

    async def get_top_buyers(
        self,
        mint: str,
        limit: int = 10,
        since_block_time: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get top buyers for a token by volume."""
        async with self.pool.acquire() as conn:
            if since_block_time:
                rows = await conn.fetch("""
                    SELECT
                        user_wallet,
                        COUNT(*) as buy_count,
                        SUM(quote_amount) as total_quote,
                        SUM(base_amount) as total_base
                    FROM swap_events
                    WHERE base_mint = $1 AND side = 'buy' AND block_time >= $2
                    GROUP BY user_wallet
                    ORDER BY total_quote DESC
                    LIMIT $3
                """, mint, since_block_time, limit)
            else:
                rows = await conn.fetch("""
                    SELECT
                        user_wallet,
                        COUNT(*) as buy_count,
                        SUM(quote_amount) as total_quote,
                        SUM(base_amount) as total_base
                    FROM swap_events
                    WHERE base_mint = $1 AND side = 'buy'
                    GROUP BY user_wallet
                    ORDER BY total_quote DESC
                    LIMIT $2
                """, mint, limit)

            return [dict(row) for row in rows]

    # ============== Wallet Profile Operations ==============

    async def get_wallet_profile(self, address: str) -> Optional[WalletProfile]:
        """Get wallet profile by address."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM wallet_profiles WHERE address = $1",
                address
            )
            if row:
                return WalletProfile(
                    address=row["address"],
                    first_seen=row["first_seen"],
                    last_seen=row["last_seen"],
                    total_buys=row["total_buys"],
                    total_sells=row["total_sells"],
                    total_volume_sol=row["total_volume_sol"],
                    tokens_traded=set(row["tokens_traded"] or []),
                    cluster_id=row["cluster_id"],
                    cluster_size=row["cluster_size"],
                    funded_by=row["funded_by"],
                    funding_amount_sol=row["funding_amount_sol"],
                    funding_hop=row["funding_hop"],
                    is_new_wallet=row["is_new_wallet"],
                    cto_score=row["cto_score"],
                )
            return None

    async def upsert_wallet_profile(self, profile: WalletProfile):
        """Insert or update wallet profile."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO wallet_profiles (
                    address, first_seen, last_seen, total_buys, total_sells,
                    total_volume_sol, tokens_traded, cluster_id, cluster_size,
                    funded_by, funding_amount_sol, funding_hop, is_new_wallet,
                    cto_score, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, NOW())
                ON CONFLICT (address) DO UPDATE SET
                    last_seen = EXCLUDED.last_seen,
                    total_buys = EXCLUDED.total_buys,
                    total_sells = EXCLUDED.total_sells,
                    total_volume_sol = EXCLUDED.total_volume_sol,
                    tokens_traded = EXCLUDED.tokens_traded,
                    cluster_id = COALESCE(EXCLUDED.cluster_id, wallet_profiles.cluster_id),
                    cluster_size = EXCLUDED.cluster_size,
                    funded_by = COALESCE(EXCLUDED.funded_by, wallet_profiles.funded_by),
                    funding_amount_sol = COALESCE(EXCLUDED.funding_amount_sol, wallet_profiles.funding_amount_sol),
                    funding_hop = EXCLUDED.funding_hop,
                    is_new_wallet = EXCLUDED.is_new_wallet,
                    cto_score = EXCLUDED.cto_score,
                    updated_at = NOW()
            """,
                profile.address,
                profile.first_seen,
                profile.last_seen,
                profile.total_buys,
                profile.total_sells,
                profile.total_volume_sol,
                list(profile.tokens_traded),
                profile.cluster_id,
                profile.cluster_size,
                profile.funded_by,
                profile.funding_amount_sol,
                profile.funding_hop,
                profile.is_new_wallet,
                profile.cto_score,
            )

    async def update_wallet_cluster(self, address: str, cluster_id: str, cluster_size: int):
        """Update wallet cluster information."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE wallet_profiles
                SET cluster_id = $2, cluster_size = $3, updated_at = NOW()
                WHERE address = $1
            """, address, cluster_id, cluster_size)

    # ============== Alert Operations ==============

    async def insert_alert(self, alert: Alert) -> int:
        """Insert an alert and return its ID."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO alerts (
                    mint, token_name, token_symbol, trigger_name, trigger_reason,
                    buy_count_5m, unique_buyers_5m, volume_sol_5m, buy_sell_ratio_5m,
                    top_buyers, cluster_summary, enrichment_degraded,
                    price_sol, mcap_sol, token_supply
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
                RETURNING id, created_at
            """,
                alert.mint,
                alert.token_name,
                alert.token_symbol,
                alert.trigger_name,
                alert.trigger_reason,
                alert.buy_count_5m,
                alert.unique_buyers_5m,
                alert.volume_sol_5m,
                alert.buy_sell_ratio_5m,
                str(alert.top_buyers),  # JSONB
                alert.cluster_summary,
                alert.enrichment_degraded,
                alert.price_sol,
                alert.mcap_sol,
                alert.token_supply,
            )
            return row["id"]

    async def update_alert_delivery(self, alert_id: int, discord: bool = False, telegram: bool = False):
        """Update alert delivery status."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE alerts
                SET discord_sent = discord_sent OR $2, telegram_sent = telegram_sent OR $3
                WHERE id = $1
            """, alert_id, discord, telegram)

    async def get_recent_alerts(self, mint: Optional[str] = None, limit: int = 50) -> List[Alert]:
        """Get recent alerts, optionally filtered by mint."""
        async with self.pool.acquire() as conn:
            if mint:
                rows = await conn.fetch("""
                    SELECT * FROM alerts WHERE mint = $1
                    ORDER BY created_at DESC LIMIT $2
                """, mint, limit)
            else:
                rows = await conn.fetch("""
                    SELECT * FROM alerts
                    ORDER BY created_at DESC LIMIT $1
                """, limit)

            return [
                Alert(
                    id=row["id"],
                    mint=row["mint"],
                    token_name=row["token_name"],
                    token_symbol=row["token_symbol"],
                    trigger_name=row["trigger_name"],
                    trigger_reason=row["trigger_reason"],
                    buy_count_5m=row["buy_count_5m"],
                    unique_buyers_5m=row["unique_buyers_5m"],
                    volume_sol_5m=row["volume_sol_5m"],
                    buy_sell_ratio_5m=row["buy_sell_ratio_5m"],
                    top_buyers=eval(row["top_buyers"]) if row["top_buyers"] else [],
                    cluster_summary=row["cluster_summary"],
                    enrichment_degraded=row["enrichment_degraded"],
                    created_at=row["created_at"],
                    discord_sent=row["discord_sent"],
                    telegram_sent=row["telegram_sent"],
                    price_sol=row["price_sol"],
                    mcap_sol=row["mcap_sol"],
                    token_supply=row["token_supply"],
                )
                for row in rows
            ]

    # ============== Cleanup Operations ==============

    async def cleanup_old_swaps(self, days: int = 30):
        """Delete swap events older than specified days."""
        async with self.pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM swap_events
                WHERE created_at < NOW() - INTERVAL '%s days'
            """, days)
            logger.info(f"Cleaned up old swap events: {result}")
