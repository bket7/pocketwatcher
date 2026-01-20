"""Tests for detection module."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from detection.counters import CounterManager, TokenStats
from detection.triggers import TriggerEvaluator, Trigger, TriggerCondition


class TestTriggerEvaluator:
    """Tests for TriggerEvaluator."""

    def setup_method(self):
        self.mock_counter_manager = MagicMock(spec=CounterManager)
        self.evaluator = TriggerEvaluator(self.mock_counter_manager)

    def test_parse_condition_gte(self):
        """Test parsing >= condition."""
        cond = self.evaluator._parse_condition("buy_count_5m >= 20")
        assert cond is not None
        assert cond.field == "buy_count_5m"
        assert cond.operator == ">="
        assert cond.value == 20.0

    def test_parse_condition_gt(self):
        """Test parsing > condition."""
        cond = self.evaluator._parse_condition("volume_sol_5m > 10")
        assert cond is not None
        assert cond.field == "volume_sol_5m"
        assert cond.operator == ">"
        assert cond.value == 10.0

    def test_parse_condition_lte(self):
        """Test parsing <= condition."""
        cond = self.evaluator._parse_condition("unique_buyers_5m <= 5")
        assert cond is not None
        assert cond.field == "unique_buyers_5m"
        assert cond.operator == "<="
        assert cond.value == 5.0

    def test_evaluate_trigger_all_pass(self):
        """Test trigger evaluation when all conditions pass."""
        trigger = Trigger(
            name="test_trigger",
            conditions=[
                TriggerCondition(field="buy_count", operator=">=", value=10),
                TriggerCondition(field="volume", operator=">", value=5),
            ]
        )
        stats = {"buy_count": 15, "volume": 10}

        result = self.evaluator._evaluate_trigger(trigger, stats)
        assert result is True

    def test_evaluate_trigger_partial_fail(self):
        """Test trigger evaluation when one condition fails."""
        trigger = Trigger(
            name="test_trigger",
            conditions=[
                TriggerCondition(field="buy_count", operator=">=", value=10),
                TriggerCondition(field="volume", operator=">", value=5),
            ]
        )
        stats = {"buy_count": 15, "volume": 3}  # volume fails

        result = self.evaluator._evaluate_trigger(trigger, stats)
        assert result is False

    def test_format_reason(self):
        """Test reason formatting."""
        trigger = Trigger(
            name="concentrated_accumulation",
            conditions=[
                TriggerCondition(field="buy_count_5m", operator=">=", value=20),
            ]
        )
        stats = {"buy_count_5m": 25}

        reason = self.evaluator._format_reason(trigger, stats)

        assert "concentrated_accumulation" in reason
        assert "buy_count_5m=25.00" in reason
        assert ">= 20" in reason


class TestTokenStats:
    """Tests for TokenStats dataclass."""

    def test_default_values(self):
        """Test default values are set correctly."""
        stats = TokenStats(mint="test_mint", window_seconds=300)

        assert stats.mint == "test_mint"
        assert stats.window_seconds == 300
        assert stats.buy_count == 0
        assert stats.sell_count == 0
        assert stats.volume_sol == 0.0
        assert stats.buy_sell_ratio == 0.0
        assert stats.top_buyers_volume == []

    def test_with_values(self):
        """Test creating stats with values."""
        stats = TokenStats(
            mint="test_mint",
            window_seconds=300,
            buy_count=50,
            sell_count=10,
            unique_buyers=15,
            volume_sol=25.5,
            buy_sell_ratio=5.0,
            top_3_volume_share=0.65,
        )

        assert stats.buy_count == 50
        assert stats.buy_sell_ratio == 5.0
        assert stats.top_3_volume_share == 0.65
