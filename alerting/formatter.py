"""Alert message formatting."""

from datetime import datetime
from typing import Dict, List, Optional

from models.profiles import Alert
from detection.counters import TokenStats
from enrichment.scoring import CTOScore


class AlertFormatter:
    """
    Formats alerts for different platforms.

    Produces consistent, informative alert messages for
    Discord and Telegram.
    """

    @staticmethod
    def format_discord_embed(
        alert: Alert,
        cto_score: Optional[CTOScore] = None,
    ) -> dict:
        """
        Format alert as Discord embed.

        Returns dict suitable for Discord webhook.
        """
        # Color based on trigger type
        color_map = {
            "concentrated_accumulation": 0xFF4444,  # Red
            "stealth_accumulation": 0xFF8800,       # Orange
            "extreme_ratio": 0xFFAA00,              # Yellow-orange
            "sybil_pattern": 0xFF0000,              # Bright red
            "whale_concentration": 0xFF6600,        # Dark orange
            "slow_stealth_accumulation": 0xAA00FF,  # Purple
            "slow_concentration": 0x8800FF,         # Deep purple
            "gradual_accumulation": 0x6600FF,       # Blue-purple
        }
        color = color_map.get(alert.trigger_name, 0x00AAFF)

        # Token display
        token_display = alert.token_symbol or alert.mint[:8] + "..."
        if alert.token_name:
            token_display = f"{alert.token_name} ({alert.token_symbol})"

        # Build fields
        fields = [
            {
                "name": "Token",
                "value": f"`{alert.mint}`",
                "inline": False,
            },
            {
                "name": "Trigger",
                "value": alert.trigger_name.replace("_", " ").title(),
                "inline": True,
            },
            {
                "name": "5m Stats",
                "value": (
                    f"Buys: {alert.buy_count_5m}\n"
                    f"Buyers: {alert.unique_buyers_5m}\n"
                    f"Volume: {alert.volume_sol_5m:.2f} SOL\n"
                    f"Ratio: {alert.buy_sell_ratio_5m:.1f}x"
                ),
                "inline": True,
            },
        ]

        # Add CTO score if available
        if cto_score:
            risk_emoji = {
                "HIGH": "\U0001F534",      # Red circle
                "MEDIUM": "\U0001F7E0",    # Orange circle
                "LOW": "\U0001F7E1",       # Yellow circle
                "MINIMAL": "\U0001F7E2",   # Green circle
            }
            risk_level = AlertFormatter._get_risk_level(cto_score)
            emoji = risk_emoji.get(risk_level, "\u26AA")  # White circle default

            fields.append({
                "name": "CTO Risk",
                "value": f"{emoji} {risk_level} ({cto_score.total_score:.0%})",
                "inline": True,
            })

        # Add top buyers if available
        if alert.top_buyers:
            buyer_lines = []
            for i, buyer in enumerate(alert.top_buyers[:5]):
                wallet = buyer.get("user_wallet", buyer.get("wallet", ""))[:8]
                volume = buyer.get("total_quote", buyer.get("volume", 0))
                if isinstance(volume, (int, float)):
                    volume_sol = volume / 1e9 if volume > 1e6 else volume
                    buyer_lines.append(f"{i+1}. `{wallet}...` - {volume_sol:.2f} SOL")
                else:
                    buyer_lines.append(f"{i+1}. `{wallet}...`")

            fields.append({
                "name": "Top Buyers",
                "value": "\n".join(buyer_lines) or "N/A",
                "inline": False,
            })

        # Add cluster summary if available
        if alert.cluster_summary:
            fields.append({
                "name": "Cluster Analysis",
                "value": alert.cluster_summary,
                "inline": False,
            })

        # Degraded warning
        if alert.enrichment_degraded:
            fields.append({
                "name": "\u26A0\uFE0F Warning",
                "value": "Enrichment degraded (credit limit)",
                "inline": False,
            })

        # Links
        links = (
            f"[Solscan](https://solscan.io/token/{alert.mint}) | "
            f"[Birdeye](https://birdeye.so/token/{alert.mint}) | "
            f"[DexScreener](https://dexscreener.com/solana/{alert.mint})"
        )

        embed = {
            "title": f"\U0001F6A8 {token_display}",
            "description": alert.trigger_reason,
            "color": color,
            "fields": fields,
            "footer": {
                "text": f"Pocketwatcher | {links}"
            },
            "timestamp": (alert.created_at or datetime.utcnow()).isoformat(),
        }

        return {"embeds": [embed]}

    @staticmethod
    def format_telegram(
        alert: Alert,
        cto_score: Optional[CTOScore] = None,
    ) -> str:
        """
        Format alert as Telegram message (Markdown).

        Returns formatted string.
        """
        # Token display
        token_display = alert.token_symbol or alert.mint[:8]
        if alert.token_name:
            token_display = f"{alert.token_name} ({alert.token_symbol})"

        # Emoji based on trigger
        trigger_emoji = {
            "concentrated_accumulation": "\U0001F534",
            "stealth_accumulation": "\U0001F7E0",
            "extreme_ratio": "\U0001F7E1",
            "sybil_pattern": "\U0001F6A8",
            "whale_concentration": "\U0001F40B",
            "slow_stealth_accumulation": "\U0001F47B",
            "slow_concentration": "\U0001F50D",
            "gradual_accumulation": "\U0001F4C8",
        }
        emoji = trigger_emoji.get(alert.trigger_name, "\U0001F514")

        lines = [
            f"{emoji} *{token_display}*",
            "",
            f"*Trigger:* {alert.trigger_name.replace('_', ' ').title()}",
            f"*Reason:* {alert.trigger_reason}",
            "",
            "*5m Stats:*",
            f"  \u2022 Buys: {alert.buy_count_5m}",
            f"  \u2022 Unique Buyers: {alert.unique_buyers_5m}",
            f"  \u2022 Volume: {alert.volume_sol_5m:.2f} SOL",
            f"  \u2022 Buy/Sell Ratio: {alert.buy_sell_ratio_5m:.1f}x",
        ]

        # Add CTO score
        if cto_score:
            risk_level = AlertFormatter._get_risk_level(cto_score)
            lines.extend([
                "",
                f"*CTO Risk:* {risk_level} ({cto_score.total_score:.0%})",
            ])
            if cto_score.evidence:
                for ev in cto_score.evidence[:2]:
                    lines.append(f"  \u2022 {ev}")

        # Add top buyers
        if alert.top_buyers:
            lines.extend(["", "*Top Buyers:*"])
            for i, buyer in enumerate(alert.top_buyers[:3]):
                wallet = buyer.get("user_wallet", buyer.get("wallet", ""))[:8]
                volume = buyer.get("total_quote", buyer.get("volume", 0))
                if isinstance(volume, (int, float)):
                    volume_sol = volume / 1e9 if volume > 1e6 else volume
                    lines.append(f"  {i+1}. `{wallet}...` - {volume_sol:.2f} SOL")

        # Add cluster summary
        if alert.cluster_summary:
            lines.extend([
                "",
                f"*Clusters:* {alert.cluster_summary}",
            ])

        # Degraded warning
        if alert.enrichment_degraded:
            lines.extend(["", "\u26A0\uFE0F _Enrichment degraded (credit limit)_"])

        # Add mint address and links
        lines.extend([
            "",
            f"`{alert.mint}`",
            "",
            f"[Solscan](https://solscan.io/token/{alert.mint}) | "
            f"[Birdeye](https://birdeye.so/token/{alert.mint}) | "
            f"[DexScreener](https://dexscreener.com/solana/{alert.mint})",
        ])

        return "\n".join(lines)

    @staticmethod
    def format_plain(
        alert: Alert,
        cto_score: Optional[CTOScore] = None,
    ) -> str:
        """Format alert as plain text (for logging)."""
        token = alert.token_symbol or alert.mint[:8]
        return (
            f"[ALERT] {token} | {alert.trigger_name} | "
            f"Buys: {alert.buy_count_5m}, Buyers: {alert.unique_buyers_5m}, "
            f"Vol: {alert.volume_sol_5m:.2f} SOL"
        )

    @staticmethod
    def _get_risk_level(score: CTOScore) -> str:
        """Get risk level from CTO score."""
        if score.total_score >= 0.7:
            return "HIGH"
        elif score.total_score >= 0.4:
            return "MEDIUM"
        elif score.total_score >= 0.2:
            return "LOW"
        else:
            return "MINIMAL"
