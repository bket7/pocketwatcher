"""Live stats and health endpoints."""

import logging
import time
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Query

from api.models import (
    AlertModel,
    AlertsResponse,
    HealthResponse,
    HotTokensResponse,
    SystemStats,
    TokenStatsModel,
)
from api.deps import get_redis, get_postgres

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stats"])

# Track API start time for uptime
_start_time = time.time()


@router.get("/stats", response_model=SystemStats)
async def get_stats():
    """Get real-time system statistics."""
    redis = await get_redis()
    postgres = await get_postgres()

    # Get stream info
    stream_info = await redis.get_stream_info()
    stream_length = stream_info.get("length", 0)

    # Calculate processing lag from stream timestamps
    processing_lag = 0.0
    if stream_info.get("last_entry"):
        try:
            # Stream entry ID format: timestamp_ms-sequence
            last_entry = stream_info["last_entry"]
            if isinstance(last_entry, (list, tuple)) and len(last_entry) > 0:
                entry_id = last_entry[0]
                if isinstance(entry_id, bytes):
                    entry_id = entry_id.decode()
                ts_ms = int(entry_id.split("-")[0])
                processing_lag = (time.time() * 1000 - ts_ms) / 1000
        except Exception as e:
            logger.debug(f"Failed to calculate lag: {e}")

    # Get HOT token count
    hot_tokens = await redis.get_hot_tokens()
    hot_count = len(hot_tokens)

    # Get alerts count for today
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    alerts_today = await postgres.fetchval(
        "SELECT COUNT(*) FROM alerts WHERE created_at >= $1",
        today_start
    ) or 0

    # Get swap count (from recent stream if available)
    # This is approximate - we'd need a proper counter for exact stats
    swaps_detected = await postgres.fetchval(
        "SELECT COUNT(*) FROM swap_events WHERE block_time >= $1",
        int(time.time()) - 3600  # Last hour
    ) or 0

    # Determine mode based on lag/stream length
    if processing_lag > 30 or stream_length > 80000:
        mode = "CRITICAL"
    elif processing_lag > 5 or stream_length > 50000:
        mode = "DEGRADED"
    else:
        mode = "NORMAL"

    # Calculate tx/s (approximate from stream length change)
    # For now, use a placeholder - real implementation would track over time
    tx_per_second = 0.0

    return SystemStats(
        tx_per_second=tx_per_second,
        swaps_detected=swaps_detected,
        hot_tokens_current=hot_count,
        alerts_today=alerts_today,
        stream_length=stream_length,
        processing_lag_seconds=processing_lag,
        mode=mode,
        uptime_seconds=time.time() - _start_time,
    )


@router.get("/alerts", response_model=AlertsResponse)
async def get_alerts(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    mint: str = Query(default=None, description="Filter by mint address"),
):
    """Get recent alerts."""
    postgres = await get_postgres()

    # Build query - include mcap fields for trading decisions
    if mint:
        rows = await postgres.fetch(
            """
            SELECT id, mint, token_name, token_symbol, trigger_name, trigger_reason,
                   buy_count_5m, unique_buyers_5m, volume_sol_5m, buy_sell_ratio_5m,
                   created_at, venue, mcap_sol, price_sol, token_image, top_buyers
            FROM alerts
            WHERE mint = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            mint, limit, offset
        )
        total = await postgres.fetchval(
            "SELECT COUNT(*) FROM alerts WHERE mint = $1", mint
        ) or 0
    else:
        rows = await postgres.fetch(
            """
            SELECT id, mint, token_name, token_symbol, trigger_name, trigger_reason,
                   buy_count_5m, unique_buyers_5m, volume_sol_5m, buy_sell_ratio_5m,
                   created_at, venue, mcap_sol, price_sol, token_image, top_buyers
            FROM alerts
            ORDER BY created_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit, offset
        )
        total = await postgres.fetchval("SELECT COUNT(*) FROM alerts") or 0

    alerts = []
    for row in rows:
        # Handle infinity values that can't be JSON serialized
        ratio = float(row.get("buy_sell_ratio_5m", 0))
        if ratio == float('inf') or ratio != ratio:  # inf or nan
            ratio = 999.0

        # Calculate avg entry mcap from top_buyers if available
        avg_entry_mcap = None
        top_buyers_raw = row.get("top_buyers")
        if top_buyers_raw:
            try:
                # top_buyers is stored as JSONB string
                import ast
                if isinstance(top_buyers_raw, str):
                    top_buyers_list = ast.literal_eval(top_buyers_raw)
                else:
                    top_buyers_list = top_buyers_raw

                # Calculate weighted avg entry mcap
                total_mcap = 0
                count = 0
                for buyer in top_buyers_list:
                    entry_mcap = buyer.get("avg_entry_mcap")
                    if entry_mcap and entry_mcap > 0:
                        total_mcap += entry_mcap
                        count += 1
                if count > 0:
                    avg_entry_mcap = total_mcap / count
            except Exception:
                pass

        # Handle mcap infinity/nan
        mcap_sol = row.get("mcap_sol")
        if mcap_sol is not None:
            if mcap_sol == float('inf') or mcap_sol != mcap_sol:
                mcap_sol = None

        alerts.append(AlertModel(
            id=row["id"],
            mint=row["mint"],
            token_name=row.get("token_name"),
            token_symbol=row.get("token_symbol"),
            trigger_name=row["trigger_name"],
            trigger_reason=row["trigger_reason"],
            buy_count_5m=row.get("buy_count_5m", 0),
            unique_buyers_5m=row.get("unique_buyers_5m", 0),
            volume_sol_5m=float(row.get("volume_sol_5m", 0)),
            buy_sell_ratio_5m=ratio,
            created_at=row["created_at"].isoformat() if row.get("created_at") else "",
            venue=row.get("venue"),
            mcap_sol=mcap_sol,
            price_sol=row.get("price_sol"),
            token_image=row.get("token_image"),
            avg_entry_mcap=avg_entry_mcap,
        ))

    return AlertsResponse(alerts=alerts, total=total)


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    details = {}

    # Check Redis
    redis_ok = False
    try:
        redis = await get_redis()
        await redis.redis.ping()
        redis_ok = True
        details["redis"] = "connected"
    except Exception as e:
        details["redis"] = f"error: {e}"

    # Check PostgreSQL
    postgres_ok = False
    try:
        postgres = await get_postgres()
        await postgres.fetchval("SELECT 1")
        postgres_ok = True
        details["postgres"] = "connected"
    except Exception as e:
        details["postgres"] = f"error: {e}"

    # Check stream activity
    stream_active = False
    last_tx_age = None
    try:
        redis = await get_redis()
        stream_info = await redis.get_stream_info()
        if stream_info.get("last_entry"):
            last_entry = stream_info["last_entry"]
            if isinstance(last_entry, (list, tuple)) and len(last_entry) > 0:
                entry_id = last_entry[0]
                if isinstance(entry_id, bytes):
                    entry_id = entry_id.decode()
                ts_ms = int(entry_id.split("-")[0])
                last_tx_age = (time.time() * 1000 - ts_ms) / 1000
                stream_active = last_tx_age < 60  # Active if tx within last minute
        details["stream_length"] = stream_info.get("length", 0)
    except Exception as e:
        details["stream"] = f"error: {e}"

    # Determine overall status
    if redis_ok and postgres_ok and stream_active:
        status = "healthy"
    elif redis_ok and postgres_ok:
        status = "degraded"  # DB ok but stream inactive
    else:
        status = "unhealthy"

    return HealthResponse(
        status=status,
        redis_connected=redis_ok,
        postgres_connected=postgres_ok,
        stream_active=stream_active,
        last_tx_age_seconds=last_tx_age,
        details=details,
    )


@router.get("/hot-tokens", response_model=HotTokensResponse)
async def get_hot_tokens():
    """Get all currently HOT tokens with their stats."""
    redis = await get_redis()

    hot_mints = await redis.get_hot_tokens()
    tokens = []

    for mint in hot_mints:
        # Get rolling stats for each token
        stats = await redis.get_rolling_stats(mint, 300)

        tokens.append(TokenStatsModel(
            mint=mint,
            buy_count_5m=stats.get("buy_count", 0),
            sell_count_5m=stats.get("sell_count", 0),
            unique_buyers_5m=stats.get("unique_buyers", 0),
            unique_sellers_5m=stats.get("unique_sellers", 0),
            buy_volume_sol_5m=stats.get("volume_sol", 0),
            avg_buy_size_5m=stats.get("avg_buy_size", 0),
            buy_sell_ratio_5m=stats.get("buy_sell_ratio", 0),
            is_hot=True,
        ))

    return HotTokensResponse(
        tokens=tokens,
        count=len(tokens),
    )


@router.get("/token/{mint}/stats", response_model=TokenStatsModel)
async def get_token_stats(mint: str):
    """Get stats for a specific token."""
    redis = await get_redis()

    stats = await redis.get_rolling_stats(mint, 300)
    is_hot = await redis.is_token_hot(mint)

    return TokenStatsModel(
        mint=mint,
        buy_count_5m=stats.get("buy_count", 0),
        sell_count_5m=stats.get("sell_count", 0),
        unique_buyers_5m=stats.get("unique_buyers", 0),
        unique_sellers_5m=stats.get("unique_sellers", 0),
        buy_volume_sol_5m=stats.get("volume_sol", 0),
        avg_buy_size_5m=stats.get("avg_buy_size", 0),
        buy_sell_ratio_5m=stats.get("buy_sell_ratio", 0),
        is_hot=is_hot,
    )
