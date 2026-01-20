"""Pydantic settings for Pocketwatcher configuration."""

from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Chainstack Yellowstone gRPC
    yellowstone_endpoint: str = Field(
        ...,
        description="Chainstack Yellowstone gRPC endpoint"
    )
    yellowstone_token: str = Field(
        ...,
        description="Chainstack Yellowstone auth token"
    )

    # Redis
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL"
    )
    redis_stream_maxlen: int = Field(
        default=100000,
        description="Max messages in Redis stream buffer"
    )
    stream_consumer_count: int = Field(
        default=1,
        description="Number of Redis stream consumers"
    )
    stream_consumer_batch_size: int = Field(
        default=100,
        description="Batch size per stream consumer read"
    )
    stream_consumer_block_ms: int = Field(
        default=1000,
        description="Blocking read timeout in milliseconds"
    )

    # PostgreSQL
    postgres_url: str = Field(
        ...,
        description="PostgreSQL connection URL"
    )

    # Helius
    helius_api_key: str = Field(
        ...,
        description="Helius API key"
    )
    helius_rpc_url: Optional[str] = Field(
        default=None,
        description="Helius RPC URL (constructed from API key if not provided)"
    )
    helius_daily_credit_limit: int = Field(
        default=300000,
        description="Daily Helius credit budget (~10M/month / 30 days)"
    )

    # Alerting
    discord_webhook_url: Optional[str] = Field(
        default=None,
        description="Discord webhook URL for alerts"
    )
    telegram_bot_token: Optional[str] = Field(
        default=None,
        description="Telegram bot token"
    )
    telegram_chat_id: Optional[str] = Field(
        default=None,
        description="Telegram chat ID for alerts"
    )

    # Detection
    dedup_ttl_seconds: int = Field(
        default=600,
        description="Signature dedup TTL (10 min default)"
    )
    delta_log_retention_minutes: int = Field(
        default=60,
        description="TxDeltaRecord retention for recovery"
    )
    min_swap_confidence: float = Field(
        default=0.7,
        description="Minimum confidence for SwapEventFull"
    )

    # Backpressure thresholds
    degraded_lag_seconds: int = Field(
        default=5,
        description="Processing lag threshold for DEGRADED mode"
    )
    critical_lag_seconds: int = Field(
        default=30,
        description="Processing lag threshold for CRITICAL mode"
    )
    degraded_stream_len: int = Field(
        default=50000,
        description="Stream length threshold for DEGRADED mode"
    )
    critical_stream_len: int = Field(
        default=80000,
        description="Stream length threshold for CRITICAL mode"
    )

    @property
    def helius_endpoint(self) -> str:
        """Get Helius RPC endpoint."""
        if self.helius_rpc_url:
            return self.helius_rpc_url
        return f"https://mainnet.helius-rpc.com/?api-key={self.helius_api_key}"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore"
    }


# Global settings instance
settings = Settings()
