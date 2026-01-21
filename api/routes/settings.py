"""Settings CRUD endpoints."""

import logging
from typing import Any, Dict

import yaml
from fastapi import APIRouter, HTTPException

from api.models import (
    AlertSettings,
    BackpressureSettings,
    DetectionSettings,
    SettingsResponse,
    SettingsUpdateRequest,
)
from api.deps import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(tags=["settings"])


async def get_setting(key: str, default: Any = None) -> Any:
    """Get a setting from Redis or return default."""
    redis = await get_redis()
    raw = await redis.get_config(key)
    if raw:
        try:
            return yaml.safe_load(raw)
        except Exception:
            pass
    return default


async def set_setting(key: str, value: Any):
    """Set a setting in Redis and notify subscribers."""
    redis = await get_redis()
    yaml_str = yaml.dump(value, default_flow_style=False)
    await redis.set_config(key, yaml_str.encode())


@router.get("/settings", response_model=SettingsResponse)
async def get_settings():
    """Get all hot-reloadable settings."""
    # Alert settings
    alerts_data = await get_setting("alerts", {})
    alerts = AlertSettings(
        discord_webhook_url=alerts_data.get("discord_webhook_url"),
        telegram_bot_token=alerts_data.get("telegram_bot_token"),
        telegram_chat_id=alerts_data.get("telegram_chat_id"),
    )

    # Backpressure settings
    bp_data = await get_setting("backpressure", {})
    backpressure = BackpressureSettings(
        degraded_lag_seconds=bp_data.get("degraded_lag_seconds", 5),
        critical_lag_seconds=bp_data.get("critical_lag_seconds", 30),
        degraded_stream_len=bp_data.get("degraded_stream_len", 50000),
        critical_stream_len=bp_data.get("critical_stream_len", 80000),
    )

    # Detection settings
    det_data = await get_setting("detection", {})
    detection = DetectionSettings(
        hot_token_ttl_seconds=det_data.get("hot_token_ttl_seconds", 3600),
        alert_cooldown_seconds=det_data.get("alert_cooldown_seconds", 300),
        min_swap_confidence=det_data.get("min_swap_confidence", 0.7),
    )

    return SettingsResponse(
        alerts=alerts,
        backpressure=backpressure,
        detection=detection,
    )


@router.put("/settings", response_model=SettingsResponse)
async def update_settings(request: SettingsUpdateRequest):
    """Update settings (only provided fields)."""
    # Update alert settings
    if request.alerts:
        current = await get_setting("alerts", {})
        if request.alerts.discord_webhook_url is not None:
            current["discord_webhook_url"] = request.alerts.discord_webhook_url
        if request.alerts.telegram_bot_token is not None:
            current["telegram_bot_token"] = request.alerts.telegram_bot_token
        if request.alerts.telegram_chat_id is not None:
            current["telegram_chat_id"] = request.alerts.telegram_chat_id
        await set_setting("alerts", current)
        logger.info("Updated alert settings")

    # Update backpressure settings
    if request.backpressure:
        bp = request.backpressure
        await set_setting("backpressure", {
            "degraded_lag_seconds": bp.degraded_lag_seconds,
            "critical_lag_seconds": bp.critical_lag_seconds,
            "degraded_stream_len": bp.degraded_stream_len,
            "critical_stream_len": bp.critical_stream_len,
        })
        logger.info("Updated backpressure settings")

    # Update detection settings
    if request.detection:
        det = request.detection
        await set_setting("detection", {
            "hot_token_ttl_seconds": det.hot_token_ttl_seconds,
            "alert_cooldown_seconds": det.alert_cooldown_seconds,
            "min_swap_confidence": det.min_swap_confidence,
        })
        logger.info("Updated detection settings")

    # Return updated settings
    return await get_settings()


@router.put("/settings/alerts", response_model=AlertSettings)
async def update_alert_settings(settings: AlertSettings):
    """Update alert channel settings."""
    data = {
        "discord_webhook_url": settings.discord_webhook_url,
        "telegram_bot_token": settings.telegram_bot_token,
        "telegram_chat_id": settings.telegram_chat_id,
    }
    await set_setting("alerts", data)
    logger.info("Updated alert settings")
    return settings


@router.put("/settings/backpressure", response_model=BackpressureSettings)
async def update_backpressure_settings(settings: BackpressureSettings):
    """Update backpressure threshold settings."""
    data = {
        "degraded_lag_seconds": settings.degraded_lag_seconds,
        "critical_lag_seconds": settings.critical_lag_seconds,
        "degraded_stream_len": settings.degraded_stream_len,
        "critical_stream_len": settings.critical_stream_len,
    }
    await set_setting("backpressure", data)
    logger.info("Updated backpressure settings")
    return settings


@router.put("/settings/detection", response_model=DetectionSettings)
async def update_detection_settings(settings: DetectionSettings):
    """Update detection parameter settings."""
    data = {
        "hot_token_ttl_seconds": settings.hot_token_ttl_seconds,
        "alert_cooldown_seconds": settings.alert_cooldown_seconds,
        "min_swap_confidence": settings.min_swap_confidence,
    }
    await set_setting("detection", data)
    logger.info("Updated detection settings")
    return settings
