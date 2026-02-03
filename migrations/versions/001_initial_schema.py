"""Initial schema from existing tables.

Revision ID: 001
Revises:
Create Date: 2026-02-03

This migration captures the existing schema. Run this on a fresh database
or skip if tables already exist.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Token profiles table
    op.execute("""
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

    # Swap events table
    op.execute("""
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
            mcap_at_swap DOUBLE PRECISION,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(signature, base_mint)
        )
    """)

    # Swap events indexes
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_swap_events_base_mint
        ON swap_events(base_mint, block_time DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_swap_events_user_wallet
        ON swap_events(user_wallet, block_time DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_swap_events_block_time
        ON swap_events(block_time DESC)
    """)

    # Wallet profiles table
    op.execute("""
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
    op.execute("""
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
            price_sol DOUBLE PRECISION,
            mcap_sol DOUBLE PRECISION,
            token_supply BIGINT,
            venue VARCHAR(50),
            token_image TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # Alerts indexes
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_alerts_mint
        ON alerts(mint, created_at DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_alerts_created_at
        ON alerts(created_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS alerts CASCADE")
    op.execute("DROP TABLE IF EXISTS wallet_profiles CASCADE")
    op.execute("DROP TABLE IF EXISTS swap_events CASCADE")
    op.execute("DROP TABLE IF EXISTS token_profiles CASCADE")
