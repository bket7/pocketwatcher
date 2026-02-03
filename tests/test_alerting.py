"""Tests for alerting module."""

import pytest
from datetime import datetime
from unittest.mock import patch

from alerting.formatter import AlertFormatter, get_sol_price_sync
from models.profiles import Alert
from enrichment.scoring import CTOScore


class TestAlertFormatter:
    """Tests for AlertFormatter."""

    def test_format_discord_embed_basic(self):
        """Test basic Discord embed formatting."""
        alert = Alert(
            mint="TokenMint123456789",
            token_name="Test Token",
            token_symbol="TEST",
            trigger_name="concentrated_accumulation",
            trigger_reason="buy_count_5m >= 20",
            buy_count_5m=25,
            unique_buyers_5m=5,
            volume_sol_5m=10.5,
            buy_sell_ratio_5m=5.0,
            top_buyers=[],
            cluster_summary="",
            enrichment_degraded=False,
            created_at=datetime.utcnow(),
        )

        result = AlertFormatter.format_discord_embed(alert)

        assert "embeds" in result
        embed = result["embeds"][0]
        assert "$TEST" in embed["title"]
        assert "Test Token" in embed["description"]
        assert "color" in embed
        assert len(embed["fields"]) > 0

    def test_format_discord_embed_with_cto_score(self):
        """Test Discord embed with CTO score."""
        alert = Alert(
            mint="TokenMint123456789",
            token_symbol="TEST",
            trigger_name="extreme_ratio",
            trigger_reason="buy_sell_ratio >= 10",
            buy_count_5m=50,
            unique_buyers_5m=10,
            volume_sol_5m=25.0,
            buy_sell_ratio_5m=15.0,
            top_buyers=[],
            cluster_summary="",
            enrichment_degraded=False,
            created_at=datetime.utcnow(),
        )

        cto_score = CTOScore(
            total_score=0.75,
            confidence=0.9,
            concentration_score=0.8,
            cluster_score=0.6,
            timing_score=0.5,
            new_wallet_score=0.3,
            ratio_score=0.9,
            evidence=["Very high concentration: top 3 = 85%"],
        )

        result = AlertFormatter.format_discord_embed(alert, cto_score)

        embed = result["embeds"][0]
        # High score should use HIGH color
        assert embed["color"] == AlertFormatter.RISK_COLORS["HIGH"]
        # Should have CTO Likelihood field
        field_names = [f["name"] for f in embed["fields"]]
        assert any("CTO" in name for name in field_names)

    def test_format_discord_embed_with_top_buyers(self):
        """Test Discord embed with top buyers list."""
        alert = Alert(
            mint="TokenMint123456789",
            token_symbol="TEST",
            trigger_name="whale_concentration",
            trigger_reason="top 3 buyers hold 80%",
            buy_count_5m=30,
            unique_buyers_5m=8,
            volume_sol_5m=50.0,
            buy_sell_ratio_5m=8.0,
            top_buyers=[
                {"user_wallet": "Wallet1111111111111111111111111111111111", "total_quote": 20_000_000_000, "avg_entry_mcap": 100},
                {"user_wallet": "Wallet2222222222222222222222222222222222", "total_quote": 15_000_000_000, "avg_entry_mcap": 150},
                {"user_wallet": "Wallet3333333333333333333333333333333333", "total_quote": 10_000_000_000},
            ],
            cluster_summary="3 wallets in 1 cluster",
            enrichment_degraded=False,
            created_at=datetime.utcnow(),
        )

        result = AlertFormatter.format_discord_embed(alert)

        embed = result["embeds"][0]
        field_names = [f["name"] for f in embed["fields"]]
        # Should have Top Buyers field
        assert any("Top Buyers" in name for name in field_names)

        # Check buyer formatting
        buyer_field = next(f for f in embed["fields"] if "Top Buyers" in f["name"])
        assert "Wallet111111" in buyer_field["value"]
        assert "SOL" in buyer_field["value"]

    def test_format_discord_embed_with_mcap(self):
        """Test Discord embed with market cap."""
        alert = Alert(
            mint="TokenMint123456789",
            token_symbol="TEST",
            trigger_name="concentrated_accumulation",
            trigger_reason="test",
            buy_count_5m=20,
            unique_buyers_5m=5,
            volume_sol_5m=10.0,
            buy_sell_ratio_5m=5.0,
            mcap_sol=5000,  # 5000 SOL mcap
            top_buyers=[],
            cluster_summary="",
            enrichment_degraded=False,
            created_at=datetime.utcnow(),
        )

        with patch('alerting.formatter.get_sol_price_sync', return_value=200.0):
            result = AlertFormatter.format_discord_embed(alert)

        embed = result["embeds"][0]
        # Description should contain mcap
        assert "mcap" in embed["description"].lower()
        assert "$" in embed["description"]

    def test_format_telegram_basic(self):
        """Test basic Telegram formatting."""
        alert = Alert(
            mint="TokenMint123456789",
            token_name="Test Token",
            token_symbol="TEST",
            trigger_name="concentrated_accumulation",
            trigger_reason="buy_count_5m >= 20",
            buy_count_5m=25,
            unique_buyers_5m=5,
            volume_sol_5m=10.5,
            buy_sell_ratio_5m=5.0,
            top_buyers=[],
            cluster_summary="",
            enrichment_degraded=False,
            created_at=datetime.utcnow(),
        )

        result = AlertFormatter.format_telegram(alert)

        assert "Test Token" in result
        assert "$TEST" in result
        assert "10.5 SOL" in result
        assert "5" in result  # unique buyers
        assert "Birdeye" in result
        assert "DexScreener" in result

    def test_format_plain(self):
        """Test plain text formatting."""
        alert = Alert(
            mint="TokenMint123456789",
            token_symbol="TEST",
            trigger_name="extreme_ratio",
            trigger_reason="test",
            buy_count_5m=50,
            unique_buyers_5m=10,
            volume_sol_5m=25.0,
            buy_sell_ratio_5m=15.0,
            top_buyers=[],
            cluster_summary="",
            enrichment_degraded=False,
            created_at=datetime.utcnow(),
        )

        cto_score = CTOScore(
            total_score=0.75,
            confidence=0.9,
        )

        result = AlertFormatter.format_plain(alert, cto_score)

        assert "[ALERT]" in result
        assert "TEST" in result
        assert "extreme_ratio" in result
        assert "25.0 SOL" in result
        assert "75%" in result

    def test_format_ratio_infinite(self):
        """Test ratio formatting with infinite value."""
        result = AlertFormatter._format_ratio(float('inf'))
        assert "ALL BUYS" in result

    def test_format_ratio_very_high(self):
        """Test ratio formatting with very high value."""
        result = AlertFormatter._format_ratio(500)
        assert "almost no sells" in result

    def test_format_ratio_normal(self):
        """Test ratio formatting with normal value."""
        result = AlertFormatter._format_ratio(5.5)
        assert "5.5x" in result

    def test_format_mcap_millions(self):
        """Test mcap formatting for millions."""
        with patch('alerting.formatter.get_sol_price_sync', return_value=200.0):
            result = AlertFormatter._format_mcap(10000)  # 10k SOL = $2M
        assert "M" in result

    def test_format_mcap_thousands(self):
        """Test mcap formatting for thousands."""
        with patch('alerting.formatter.get_sol_price_sync', return_value=200.0):
            result = AlertFormatter._format_mcap(100)  # 100 SOL = $20K
        assert "K" in result

    def test_get_risk_level_critical(self):
        """Test risk level determination - critical."""
        score = CTOScore(total_score=0.85, confidence=0.9)
        result = AlertFormatter._get_risk_level(score)
        assert result == "CRITICAL"

    def test_get_risk_level_high(self):
        """Test risk level determination - high."""
        score = CTOScore(total_score=0.65, confidence=0.9)
        result = AlertFormatter._get_risk_level(score)
        assert result == "HIGH"

    def test_get_risk_level_medium(self):
        """Test risk level determination - medium."""
        score = CTOScore(total_score=0.45, confidence=0.9)
        result = AlertFormatter._get_risk_level(score)
        assert result == "MEDIUM"

    def test_get_risk_level_low(self):
        """Test risk level determination - low."""
        score = CTOScore(total_score=0.25, confidence=0.9)
        result = AlertFormatter._get_risk_level(score)
        assert result == "LOW"

    def test_get_risk_level_minimal(self):
        """Test risk level determination - minimal."""
        score = CTOScore(total_score=0.1, confidence=0.9)
        result = AlertFormatter._get_risk_level(score)
        assert result == "MINIMAL"

    def test_venue_badges(self):
        """Test that venue badges are included."""
        for venue in ["pump", "jupiter", "raydium"]:
            alert = Alert(
                mint="TokenMint123456789",
                token_symbol="TEST",
                trigger_name="test",
                trigger_reason="test",
                buy_count_5m=20,
                unique_buyers_5m=5,
                volume_sol_5m=10.0,
                buy_sell_ratio_5m=5.0,
                venue=venue,
                top_buyers=[],
                cluster_summary="",
                enrichment_degraded=False,
                created_at=datetime.utcnow(),
            )

            result = AlertFormatter.format_discord_embed(alert)
            embed = result["embeds"][0]
            venue_name = AlertFormatter.VENUE_INFO[venue][1]
            assert venue_name in embed["description"]

    def test_enrichment_degraded_warning(self):
        """Test that degraded warning is shown."""
        alert = Alert(
            mint="TokenMint123456789",
            token_symbol="TEST",
            trigger_name="test",
            trigger_reason="test",
            buy_count_5m=20,
            unique_buyers_5m=5,
            volume_sol_5m=10.0,
            buy_sell_ratio_5m=5.0,
            top_buyers=[],
            cluster_summary="",
            enrichment_degraded=True,
            created_at=datetime.utcnow(),
        )

        result = AlertFormatter.format_discord_embed(alert)
        embed = result["embeds"][0]

        field_names = [f["name"] for f in embed["fields"]]
        assert any("Limited" in name for name in field_names)

    def test_token_image_thumbnail(self):
        """Test that token image is added as thumbnail."""
        alert = Alert(
            mint="TokenMint123456789",
            token_symbol="TEST",
            trigger_name="test",
            trigger_reason="test",
            buy_count_5m=20,
            unique_buyers_5m=5,
            volume_sol_5m=10.0,
            buy_sell_ratio_5m=5.0,
            token_image="https://example.com/token.png",
            top_buyers=[],
            cluster_summary="",
            enrichment_degraded=False,
            created_at=datetime.utcnow(),
        )

        result = AlertFormatter.format_discord_embed(alert)
        embed = result["embeds"][0]

        assert "thumbnail" in embed
        assert embed["thumbnail"]["url"] == "https://example.com/token.png"
