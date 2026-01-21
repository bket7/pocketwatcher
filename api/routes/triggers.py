"""Trigger CRUD endpoints."""

import logging
from typing import List, Optional

import yaml
from fastapi import APIRouter, HTTPException

from api.models import (
    TriggerConfigRequest,
    TriggerConfigResponse,
    TriggerModel,
    TriggerValidationResponse,
)
from api.deps import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(tags=["triggers"])

CONFIG_FILE = "config/thresholds.yaml"


def load_triggers_from_file() -> List[TriggerModel]:
    """Load triggers from YAML file."""
    try:
        with open(CONFIG_FILE, "r") as f:
            config = yaml.safe_load(f)

        triggers = []
        for t in config.get("triggers", []):
            triggers.append(TriggerModel(
                name=t.get("name", "unknown"),
                conditions=t.get("conditions", []),
                enabled=t.get("enabled", True),
            ))
        return triggers
    except Exception as e:
        logger.error(f"Failed to load triggers from file: {e}")
        return []


def validate_condition(cond_str: str) -> Optional[str]:
    """Validate a condition string. Returns error message or None if valid."""
    valid_fields = {
        # 5-minute stats
        "buy_count_5m", "sell_count_5m", "unique_buyers_5m", "unique_sellers_5m",
        "buy_volume_sol_5m", "avg_buy_size_5m", "buy_sell_ratio_5m",
        "top_3_buyers_volume_share_5m", "new_wallet_pct_5m",
        # 1-hour stats
        "buy_count_1h", "sell_count_1h", "unique_buyers_1h", "unique_sellers_1h",
        "buy_volume_sol_1h", "avg_buy_size_1h", "buy_sell_ratio_1h",
        "top_3_buyers_volume_share_1h", "new_wallet_pct_1h",
    }
    valid_operators = [">=", "<=", "==", ">", "<"]

    # Parse condition
    parsed_op = None
    for op in [">=", "<=", "==", ">", "<"]:
        if op in cond_str:
            parsed_op = op
            break

    if not parsed_op:
        return f"Invalid operator in '{cond_str}'. Use one of: {valid_operators}"

    parts = cond_str.split(parsed_op)
    if len(parts) != 2:
        return f"Invalid condition format: '{cond_str}'"

    field = parts[0].strip()
    value_str = parts[1].strip()

    if field not in valid_fields:
        return f"Unknown field '{field}'. Valid fields: {sorted(valid_fields)}"

    try:
        float(value_str)
    except ValueError:
        return f"Invalid value '{value_str}' - must be a number"

    return None


def validate_triggers(triggers: List[TriggerModel]) -> List[str]:
    """Validate all triggers. Returns list of errors."""
    errors = []
    names_seen = set()

    for i, trigger in enumerate(triggers):
        # Check unique name
        if trigger.name in names_seen:
            errors.append(f"Duplicate trigger name: '{trigger.name}'")
        names_seen.add(trigger.name)

        # Check has conditions
        if not trigger.conditions:
            errors.append(f"Trigger '{trigger.name}' has no conditions")
            continue

        # Validate each condition
        for cond in trigger.conditions:
            error = validate_condition(cond)
            if error:
                errors.append(f"Trigger '{trigger.name}': {error}")

    return errors


@router.get("/triggers", response_model=TriggerConfigResponse)
async def get_triggers():
    """Get current trigger configuration."""
    redis = await get_redis()

    # Try Redis first
    raw = await redis.get_config("thresholds")
    if raw:
        try:
            config = yaml.safe_load(raw)
            triggers = []
            for t in config.get("triggers", []):
                triggers.append(TriggerModel(
                    name=t.get("name", "unknown"),
                    conditions=t.get("conditions", []),
                    enabled=t.get("enabled", True),
                ))
            return TriggerConfigResponse(
                triggers=triggers,
                trigger_count=len(triggers),
            )
        except Exception as e:
            logger.warning(f"Failed to parse Redis config: {e}")

    # Fall back to file
    triggers = load_triggers_from_file()
    return TriggerConfigResponse(
        triggers=triggers,
        trigger_count=len(triggers),
    )


@router.put("/triggers", response_model=TriggerConfigResponse)
async def update_triggers(config: TriggerConfigRequest):
    """Update all triggers (replaces existing config)."""
    # Validate first
    errors = validate_triggers(config.triggers)
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    # Build YAML config
    yaml_config = {
        "triggers": [
            {
                "name": t.name,
                "conditions": t.conditions,
                "enabled": t.enabled,
            }
            for t in config.triggers
        ]
    }

    # Store in Redis and publish reload
    redis = await get_redis()
    yaml_str = yaml.dump(yaml_config, default_flow_style=False)
    await redis.set_config("thresholds", yaml_str.encode())

    logger.info(f"Updated triggers config with {len(config.triggers)} triggers")

    return TriggerConfigResponse(
        triggers=config.triggers,
        trigger_count=len(config.triggers),
    )


@router.post("/triggers/validate", response_model=TriggerValidationResponse)
async def validate_trigger_config(config: TriggerConfigRequest):
    """Validate trigger config without saving."""
    errors = validate_triggers(config.triggers)

    return TriggerValidationResponse(
        valid=len(errors) == 0,
        errors=errors,
        parsed_count=len(config.triggers) if not errors else 0,
    )


@router.post("/triggers/reset")
async def reset_triggers():
    """Reset triggers to file defaults (clear Redis override)."""
    redis = await get_redis()

    # Delete Redis config to fall back to file
    await redis.redis.delete("cfg:thresholds")

    # Publish reload notification
    await redis.redis.publish("cfg:reload", "thresholds")

    triggers = load_triggers_from_file()
    logger.info(f"Reset triggers to file defaults ({len(triggers)} triggers)")

    return TriggerConfigResponse(
        triggers=triggers,
        trigger_count=len(triggers),
    )
