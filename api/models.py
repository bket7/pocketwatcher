"""Pydantic models for API requests and responses."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ============== Trigger Models ==============

class TriggerConditionModel(BaseModel):
    """A single trigger condition."""
    field: str = Field(..., description="Stats field to check (e.g. buy_count_5m)")
    operator: str = Field(..., description="Comparison operator (>=, >, <=, <, ==)")
    value: float = Field(..., description="Threshold value")


class TriggerModel(BaseModel):
    """A trigger definition."""
    name: str = Field(..., description="Unique trigger name")
    conditions: List[str] = Field(
        ...,
        description="List of condition strings like 'buy_count_5m >= 20'"
    )
    enabled: bool = Field(default=True, description="Whether trigger is active")


class TriggerConfigRequest(BaseModel):
    """Request to update all triggers."""
    triggers: List[TriggerModel]


class TriggerConfigResponse(BaseModel):
    """Response with current trigger configuration."""
    triggers: List[TriggerModel]
    trigger_count: int


class TriggerValidationResponse(BaseModel):
    """Response from trigger validation."""
    valid: bool
    errors: List[str] = []
    parsed_count: int = 0


# ============== Settings Models ==============

class AlertSettings(BaseModel):
    """Alert channel settings."""
    discord_webhook_url: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None


class BackpressureSettings(BaseModel):
    """Backpressure threshold settings."""
    degraded_lag_seconds: int = 5
    critical_lag_seconds: int = 30
    degraded_stream_len: int = 50000
    critical_stream_len: int = 80000


class DetectionSettings(BaseModel):
    """Detection parameter settings."""
    hot_token_ttl_seconds: int = 3600
    alert_cooldown_seconds: int = 300
    min_swap_confidence: float = 0.7


class SettingsResponse(BaseModel):
    """Full settings response."""
    alerts: AlertSettings
    backpressure: BackpressureSettings
    detection: DetectionSettings


class SettingsUpdateRequest(BaseModel):
    """Request to update settings."""
    alerts: Optional[AlertSettings] = None
    backpressure: Optional[BackpressureSettings] = None
    detection: Optional[DetectionSettings] = None


# ============== Stats Models ==============

class SystemStats(BaseModel):
    """Real-time system statistics."""
    tx_per_second: float
    swaps_detected: int
    hot_tokens_current: int
    alerts_today: int
    stream_length: int
    processing_lag_seconds: float
    mode: str  # NORMAL, DEGRADED, CRITICAL
    uptime_seconds: float


class AlertModel(BaseModel):
    """Alert record."""
    id: int
    mint: str
    token_name: Optional[str]
    token_symbol: Optional[str]
    trigger_name: str
    trigger_reason: str
    buy_count_5m: int
    unique_buyers_5m: int
    volume_sol_5m: float
    buy_sell_ratio_5m: float
    created_at: str
    venue: Optional[str] = None


class AlertsResponse(BaseModel):
    """Response with recent alerts."""
    alerts: List[AlertModel]
    total: int


class HealthResponse(BaseModel):
    """Health check response."""
    status: str  # healthy, degraded, unhealthy
    redis_connected: bool
    postgres_connected: bool
    stream_active: bool
    last_tx_age_seconds: Optional[float]
    details: Dict[str, Any] = {}


# ============== Token Stats Models ==============

class TokenStatsModel(BaseModel):
    """Statistics for a single token."""
    mint: str
    buy_count_5m: int = 0
    sell_count_5m: int = 0
    unique_buyers_5m: int = 0
    unique_sellers_5m: int = 0
    buy_volume_sol_5m: float = 0
    avg_buy_size_5m: float = 0
    buy_sell_ratio_5m: float = 0
    top_3_buyers_volume_share_5m: float = 0
    new_wallet_pct_5m: float = 0
    is_hot: bool = False


class HotTokensResponse(BaseModel):
    """Response with HOT tokens and their stats."""
    tokens: List[TokenStatsModel]
    count: int
