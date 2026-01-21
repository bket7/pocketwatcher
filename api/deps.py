"""API dependencies and shared state."""

import logging
from typing import Optional

from storage.redis_client import RedisClient
from storage.postgres_client import PostgresClient

logger = logging.getLogger(__name__)

# Shared clients (initialized on startup)
_redis_client: Optional[RedisClient] = None
_postgres_client: Optional[PostgresClient] = None


async def init_clients():
    """Initialize shared clients."""
    global _redis_client, _postgres_client

    logger.info("Initializing API clients...")

    _redis_client = RedisClient()
    await _redis_client.connect()

    _postgres_client = PostgresClient()
    await _postgres_client.connect()

    logger.info("API clients initialized")


async def close_clients():
    """Close shared clients."""
    global _redis_client, _postgres_client

    if _redis_client:
        await _redis_client.close()
        _redis_client = None

    if _postgres_client:
        await _postgres_client.close()
        _postgres_client = None

    logger.info("API clients closed")


async def get_redis() -> RedisClient:
    """Get Redis client."""
    if _redis_client is None:
        raise RuntimeError("Redis client not initialized")
    return _redis_client


async def get_postgres() -> PostgresClient:
    """Get PostgreSQL client."""
    if _postgres_client is None:
        raise RuntimeError("PostgreSQL client not initialized")
    return _postgres_client
