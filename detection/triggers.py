"""Trigger evaluation for HOT token detection."""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import yaml

from .counters import CounterManager, TokenStats

logger = logging.getLogger(__name__)


@dataclass
class TriggerResult:
    """Result of trigger evaluation."""
    triggered: bool
    trigger_name: str
    reason: str
    stats: TokenStats


@dataclass
class TriggerCondition:
    """A single trigger condition."""
    field: str
    operator: str  # >=, >, <=, <, ==
    value: float


@dataclass
class Trigger:
    """A trigger definition with multiple conditions."""
    name: str
    conditions: List[TriggerCondition]


class TriggerEvaluator:
    """
    Evaluates detection triggers against token statistics.

    Triggers are defined in config/thresholds.yaml and support:
    - Multiple conditions (AND logic)
    - 5-minute and 1-hour windows
    - Hot reloading from Redis
    """

    def __init__(
        self,
        counter_manager: CounterManager,
        config_file: str = "config/thresholds.yaml",
    ):
        self.counters = counter_manager
        self.config_file = config_file
        self._triggers_5m: List[Trigger] = []
        self._triggers_1h: List[Trigger] = []
        self._evaluations = 0
        self._triggers_fired = 0

    async def load_config(self):
        """Load trigger configuration from file."""
        try:
            with open(self.config_file, "r") as f:
                config = yaml.safe_load(f)

            self._triggers_5m = []
            self._triggers_1h = []

            for trigger_def in config.get("triggers", []):
                trigger = self._parse_trigger(trigger_def)
                if trigger:
                    # Categorize by window
                    has_1h = any("_1h" in c.field for c in trigger.conditions)
                    if has_1h:
                        self._triggers_1h.append(trigger)
                    else:
                        self._triggers_5m.append(trigger)

            logger.info(
                f"Loaded {len(self._triggers_5m)} 5m triggers and "
                f"{len(self._triggers_1h)} 1h triggers"
            )

        except Exception as e:
            logger.error(f"Failed to load trigger config: {e}")
            raise

    def _parse_trigger(self, trigger_def: dict) -> Optional[Trigger]:
        """Parse a trigger definition from config."""
        name = trigger_def.get("name", "unknown")
        conditions = []

        for cond_str in trigger_def.get("conditions", []):
            cond = self._parse_condition(cond_str)
            if cond:
                conditions.append(cond)

        if not conditions:
            logger.warning(f"Trigger {name} has no valid conditions")
            return None

        return Trigger(name=name, conditions=conditions)

    def _parse_condition(self, cond_str: str) -> Optional[TriggerCondition]:
        """Parse a condition string like 'buy_count_5m >= 20'."""
        # Support operators: >=, >, <=, <, ==
        for op in [">=", "<=", "==", ">", "<"]:
            if op in cond_str:
                parts = cond_str.split(op)
                if len(parts) == 2:
                    field = parts[0].strip()
                    try:
                        value = float(parts[1].strip())
                        return TriggerCondition(field=field, operator=op, value=value)
                    except ValueError:
                        logger.warning(f"Invalid condition value: {cond_str}")
                        return None

        logger.warning(f"Could not parse condition: {cond_str}")
        return None

    async def evaluate(self, mint: str) -> Optional[TriggerResult]:
        """
        Evaluate all triggers for a token.

        Returns:
            TriggerResult if any trigger fires, None otherwise
        """
        self._evaluations += 1

        # Get stats for both windows
        stats_5m = await self.counters.get_stats(mint, 300)
        stats_1h = await self.counters.get_stats(mint, 3600)

        # Build combined stats dict for evaluation
        stats_dict = self._stats_to_dict(stats_5m, stats_1h)

        # Evaluate 5-minute triggers first (faster detection)
        for trigger in self._triggers_5m:
            if self._evaluate_trigger(trigger, stats_dict):
                self._triggers_fired += 1
                reason = self._format_reason(trigger, stats_dict)
                return TriggerResult(
                    triggered=True,
                    trigger_name=trigger.name,
                    reason=reason,
                    stats=stats_5m,
                )

        # Evaluate 1-hour triggers (slower stealth detection)
        for trigger in self._triggers_1h:
            if self._evaluate_trigger(trigger, stats_dict):
                self._triggers_fired += 1
                reason = self._format_reason(trigger, stats_dict)
                return TriggerResult(
                    triggered=True,
                    trigger_name=trigger.name,
                    reason=reason,
                    stats=stats_1h,
                )

        return None

    def _stats_to_dict(
        self,
        stats_5m: TokenStats,
        stats_1h: TokenStats
    ) -> Dict[str, float]:
        """Convert stats to a flat dict for condition evaluation."""
        return {
            # 5-minute stats
            "buy_count_5m": stats_5m.buy_count,
            "sell_count_5m": stats_5m.sell_count,
            "unique_buyers_5m": stats_5m.unique_buyers,
            "unique_sellers_5m": stats_5m.unique_sellers,
            "buy_volume_sol_5m": stats_5m.volume_sol,
            "avg_buy_size_5m": stats_5m.avg_buy_size,
            "buy_sell_ratio_5m": stats_5m.buy_sell_ratio,
            "top_3_buyers_volume_share_5m": stats_5m.top_3_volume_share,
            "new_wallet_pct_5m": stats_5m.new_wallet_pct,

            # 1-hour stats
            "buy_count_1h": stats_1h.buy_count,
            "sell_count_1h": stats_1h.sell_count,
            "unique_buyers_1h": stats_1h.unique_buyers,
            "unique_sellers_1h": stats_1h.unique_sellers,
            "buy_volume_sol_1h": stats_1h.volume_sol,
            "avg_buy_size_1h": stats_1h.avg_buy_size,
            "buy_sell_ratio_1h": stats_1h.buy_sell_ratio,
            "top_3_buyers_volume_share_1h": stats_1h.top_3_volume_share,
            "new_wallet_pct_1h": stats_1h.new_wallet_pct,
        }

    def _evaluate_trigger(
        self,
        trigger: Trigger,
        stats: Dict[str, float]
    ) -> bool:
        """Evaluate a single trigger (all conditions must match)."""
        for cond in trigger.conditions:
            value = stats.get(cond.field, 0)

            if cond.operator == ">=" and not (value >= cond.value):
                return False
            elif cond.operator == ">" and not (value > cond.value):
                return False
            elif cond.operator == "<=" and not (value <= cond.value):
                return False
            elif cond.operator == "<" and not (value < cond.value):
                return False
            elif cond.operator == "==" and not (value == cond.value):
                return False

        return True

    def _format_reason(
        self,
        trigger: Trigger,
        stats: Dict[str, float]
    ) -> str:
        """Format human-readable trigger reason."""
        parts = [f"Trigger: {trigger.name}"]

        for cond in trigger.conditions:
            actual = stats.get(cond.field, 0)
            parts.append(f"{cond.field}={actual:.2f} ({cond.operator} {cond.value})")

        return " | ".join(parts)

    async def evaluate_all_active(self) -> List[TriggerResult]:
        """Evaluate all active mints and return triggered results."""
        results = []
        active_mints = await self.counters.get_active_mints()

        for mint in active_mints:
            result = await self.evaluate(mint)
            if result:
                results.append(result)

        return results

    def get_stats(self) -> dict:
        """Get evaluator statistics."""
        return {
            "triggers_5m_count": len(self._triggers_5m),
            "triggers_1h_count": len(self._triggers_1h),
            "evaluations": self._evaluations,
            "triggers_fired": self._triggers_fired,
            "fire_rate_pct": (
                self._triggers_fired / self._evaluations * 100
                if self._evaluations > 0
                else 0
            ),
        }
