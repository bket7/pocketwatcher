"""Backtest endpoints - show alert performance over time."""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Query, BackgroundTasks

from api.models import (
    BacktestResponse,
    BacktestResult,
    BacktestSummary,
    TriggerPerformance,
)
from api.deps import get_redis, get_postgres
from scripts.gmgn_client import DexScreenerClient, TokenData

logger = logging.getLogger(__name__)

router = APIRouter(tags=["backtest"])

# Background refresh state
_refresh_lock = asyncio.Lock()
_last_refresh: Dict[int, float] = {}  # hours -> timestamp


async def fetch_token_price_cached(
    client: DexScreenerClient,
    redis,
    mint: str,
) -> Optional[TokenData]:
    """Fetch token price with Redis caching."""
    # Check cache first
    cached = await redis.get_token_price_cache(mint)
    if cached:
        try:
            data = json.loads(cached)
            return TokenData(
                mint=mint,
                price_usd=data.get("price_usd"),
                market_cap_usd=data.get("market_cap_usd"),
                symbol=data.get("symbol"),
                name=data.get("name"),
                success=True,
                source="cache",
            )
        except Exception:
            pass

    # Fetch from API
    result = await client.get_token(mint)

    # Cache if successful
    if result.success:
        cache_data = json.dumps({
            "price_usd": result.price_usd,
            "market_cap_usd": result.market_cap_usd,
            "symbol": result.symbol,
            "name": result.name,
        })
        await redis.set_token_price_cache(mint, cache_data.encode(), ttl_seconds=3600)

    return result


async def compute_backtest(hours: int) -> BacktestResponse:
    """Compute backtest results for alerts in the given time period."""
    redis = await get_redis()
    postgres = await get_postgres()

    # Get alerts from the time period
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    rows = await postgres.fetch(
        """
        SELECT id, mint, token_name, token_symbol, trigger_name,
               mcap_sol, price_sol, token_image, created_at
        FROM alerts
        WHERE created_at >= $1
        ORDER BY created_at DESC
        """,
        since
    )

    if not rows:
        return BacktestResponse(
            summary=BacktestSummary(
                period_hours=hours,
                total_alerts=0,
                with_price_data=0,
                dead_tokens=0,
                win_rate=None,
                avg_gain_pct=None,
            ),
            by_trigger=[],
            results=[],
            cache_age_seconds=0,
        )

    # Get current prices for all unique mints
    unique_mints = list(set(row["mint"] for row in rows))
    current_prices: Dict[str, TokenData] = {}

    async with DexScreenerClient() as client:
        for mint in unique_mints:
            try:
                current_prices[mint] = await fetch_token_price_cached(client, redis, mint)
                await asyncio.sleep(0.2)  # Rate limit
            except Exception as e:
                logger.warning(f"Failed to fetch price for {mint}: {e}")
                current_prices[mint] = TokenData(mint=mint, success=False, error=str(e))

    # Get SOL price for USD conversion
    sol_price_usd = 200.0  # Default fallback
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.get(
                "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
            )
            if resp.status_code == 200:
                data = resp.json()
                sol_price_usd = data.get("solana", {}).get("usd", 200.0)
    except Exception as e:
        logger.warning(f"Failed to fetch SOL price: {e}")

    # Build results
    results: List[BacktestResult] = []
    trigger_stats: Dict[str, Dict] = {}

    for row in rows:
        mint = row["mint"]
        trigger = row["trigger_name"]
        created_at = row["created_at"]

        # Calculate age in hours
        age_hours = (datetime.now(timezone.utc) - created_at.replace(tzinfo=timezone.utc)).total_seconds() / 3600

        # Get alert mcap in USD
        alert_mcap_sol = row.get("mcap_sol")
        alert_mcap_usd = None
        if alert_mcap_sol is not None:
            try:
                if alert_mcap_sol != float('inf') and alert_mcap_sol == alert_mcap_sol:
                    alert_mcap_usd = alert_mcap_sol * sol_price_usd
            except:
                pass

        # Get current mcap
        current_data = current_prices.get(mint)
        current_mcap_usd = None
        status = "dead"
        gain_pct = None

        if current_data and current_data.success and current_data.market_cap_usd:
            current_mcap_usd = current_data.market_cap_usd

            if alert_mcap_usd and alert_mcap_usd > 0:
                gain_pct = ((current_mcap_usd - alert_mcap_usd) / alert_mcap_usd) * 100
                status = "winner" if gain_pct > 0 else "loser"

        # Use current data for symbol/name if available, fallback to alert data
        symbol = None
        name = None
        if current_data and current_data.success:
            symbol = current_data.symbol
            name = current_data.name
        if not symbol:
            symbol = row.get("token_symbol")
        if not name:
            name = row.get("token_name")

        result = BacktestResult(
            mint=mint,
            symbol=symbol,
            name=name,
            token_image=row.get("token_image"),
            trigger=trigger,
            alert_mcap_usd=alert_mcap_usd,
            current_mcap_usd=current_mcap_usd,
            gain_pct=gain_pct,
            status=status,
            age_hours=round(age_hours, 1),
            created_at=created_at.isoformat() if created_at else "",
        )
        results.append(result)

        # Track trigger stats
        if trigger not in trigger_stats:
            trigger_stats[trigger] = {
                "alerts": 0,
                "with_price_data": 0,
                "gains": [],
            }
        trigger_stats[trigger]["alerts"] += 1
        if gain_pct is not None:
            trigger_stats[trigger]["with_price_data"] += 1
            trigger_stats[trigger]["gains"].append(gain_pct)

    # Sort results by gain (best first), dead tokens last
    results.sort(key=lambda r: (r.status == "dead", -(r.gain_pct or -float('inf'))))

    # Calculate trigger performance
    by_trigger: List[TriggerPerformance] = []
    for trigger, stats in trigger_stats.items():
        gains = stats["gains"]
        win_rate = None
        avg_gain = None
        best_gain = None
        worst_gain = None

        if gains:
            winners = sum(1 for g in gains if g > 0)
            win_rate = winners / len(gains)
            avg_gain = sum(gains) / len(gains)
            best_gain = max(gains)
            worst_gain = min(gains)

        by_trigger.append(TriggerPerformance(
            name=trigger,
            alerts=stats["alerts"],
            with_price_data=stats["with_price_data"],
            win_rate=win_rate,
            avg_gain_pct=avg_gain,
            best_gain_pct=best_gain,
            worst_gain_pct=worst_gain,
        ))

    # Sort triggers by win rate (best first)
    by_trigger.sort(key=lambda t: (-(t.win_rate or 0), -t.alerts))

    # Calculate summary
    all_gains = [r.gain_pct for r in results if r.gain_pct is not None]
    with_price_data = len(all_gains)
    dead_tokens = sum(1 for r in results if r.status == "dead")

    summary_win_rate = None
    summary_avg_gain = None
    best_result = None
    worst_result = None

    if all_gains:
        winners = sum(1 for g in all_gains if g > 0)
        summary_win_rate = winners / len(all_gains)
        summary_avg_gain = sum(all_gains) / len(all_gains)

        best_idx = all_gains.index(max(all_gains))
        worst_idx = all_gains.index(min(all_gains))

        # Find the actual result objects
        results_with_gains = [r for r in results if r.gain_pct is not None]
        if results_with_gains:
            best_r = max(results_with_gains, key=lambda r: r.gain_pct or -float('inf'))
            worst_r = min(results_with_gains, key=lambda r: r.gain_pct or float('inf'))
            best_result = {"symbol": best_r.symbol, "gain_pct": best_r.gain_pct}
            worst_result = {"symbol": worst_r.symbol, "gain_pct": worst_r.gain_pct}

    summary = BacktestSummary(
        period_hours=hours,
        total_alerts=len(results),
        with_price_data=with_price_data,
        dead_tokens=dead_tokens,
        win_rate=summary_win_rate,
        avg_gain_pct=summary_avg_gain,
        best=best_result,
        worst=worst_result,
    )

    return BacktestResponse(
        summary=summary,
        by_trigger=by_trigger,
        results=results,
        cache_age_seconds=0,
    )


async def refresh_backtest_cache(hours: int):
    """Refresh backtest cache in background."""
    async with _refresh_lock:
        try:
            logger.info(f"Refreshing backtest cache for {hours}h period...")
            redis = await get_redis()

            result = await compute_backtest(hours)

            # Cache the result
            cache_data = result.model_dump_json()

            # TTL: 5 min for 24h, 15 min for 7d/30d
            ttl = 300 if hours <= 24 else 900
            await redis.set_backtest_cache(hours, cache_data.encode(), ttl_seconds=ttl)
            await redis.set_backtest_timestamp(hours, int(time.time()), ttl_seconds=ttl)

            _last_refresh[hours] = time.time()
            logger.info(f"Backtest cache refreshed for {hours}h: {result.summary.total_alerts} alerts")

        except Exception as e:
            logger.error(f"Failed to refresh backtest cache: {e}")


@router.get("/backtest", response_model=BacktestResponse)
async def get_backtest(
    hours: int = Query(default=24, ge=1, le=720),
    background_tasks: BackgroundTasks = None,
):
    """
    Get backtest results showing alert performance.

    Returns cached results if available, triggers background refresh if stale.
    """
    redis = await get_redis()

    # Try to get cached result
    cached = await redis.get_backtest_cache(hours)
    cache_timestamp = await redis.get_backtest_timestamp(hours)

    if cached:
        try:
            data = json.loads(cached)

            # Calculate cache age
            cache_age = 0
            if cache_timestamp:
                cache_age = int(time.time() - cache_timestamp)
            data["cache_age_seconds"] = cache_age

            # Trigger background refresh if cache is getting old
            max_age = 240 if hours <= 24 else 600  # 4 min for 24h, 10 min for longer
            if cache_age > max_age and background_tasks:
                background_tasks.add_task(refresh_backtest_cache, hours)

            return BacktestResponse(**data)
        except Exception as e:
            logger.warning(f"Failed to parse cached backtest: {e}")

    # No cache - compute synchronously (first request)
    result = await compute_backtest(hours)

    # Cache the result
    cache_data = result.model_dump_json()
    ttl = 300 if hours <= 24 else 900
    await redis.set_backtest_cache(hours, cache_data.encode(), ttl_seconds=ttl)
    await redis.set_backtest_timestamp(hours, int(time.time()), ttl_seconds=ttl)

    return result


@router.post("/backtest/refresh")
async def refresh_backtest(
    hours: int = Query(default=24, ge=1, le=720),
):
    """Force refresh backtest cache."""
    await refresh_backtest_cache(hours)

    redis = await get_redis()
    cached = await redis.get_backtest_cache(hours)

    if cached:
        data = json.loads(cached)
        data["cache_age_seconds"] = 0
        return BacktestResponse(**data)

    return {"status": "refresh_failed"}


async def start_background_refresh():
    """Start periodic background refresh of backtest caches."""
    while True:
        try:
            # Refresh 24h cache every 5 minutes
            await refresh_backtest_cache(24)
            await asyncio.sleep(60)  # Wait 1 min between different periods

            # Refresh 7d cache every 15 minutes (168 hours)
            now = time.time()
            if now - _last_refresh.get(168, 0) > 900:
                await refresh_backtest_cache(168)

            await asyncio.sleep(240)  # Wait 4 min before next cycle

        except Exception as e:
            logger.error(f"Background refresh error: {e}")
            await asyncio.sleep(60)
