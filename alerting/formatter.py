"""Alert message formatting - clean, scannable Discord embeds."""

from datetime import datetime
from typing import Dict, List, Optional, Any

from models.profiles import Alert
from detection.counters import TokenStats
from enrichment.scoring import CTOScore


class AlertFormatter:
    """
    Formats alerts for Discord with clean, scannable embeds.

    Design goals:
    - Instantly scannable risk level
    - Clear evidence for WHY this was flagged
    - One-click links to investigate
    - Cluster info when suspicious patterns found
    """

    # Risk level colors and emojis
    RISK_COLORS = {
        "CRITICAL": 0xFF0000,   # Bright red
        "HIGH": 0xFF4400,       # Red-orange
        "MEDIUM": 0xFFAA00,     # Orange
        "LOW": 0xFFDD00,        # Yellow
        "MINIMAL": 0x00AA00,   # Green
    }

    RISK_EMOJI = {
        "CRITICAL": "\U0001F6A8",  # Rotating light
        "HIGH": "\U0001F534",      # Red circle
        "MEDIUM": "\U0001F7E0",    # Orange circle
        "LOW": "\U0001F7E1",       # Yellow circle
        "MINIMAL": "\U0001F7E2",   # Green circle
    }

    TRIGGER_DESCRIPTIONS = {
        "concentrated_accumulation": "Few wallets accumulating aggressively",
        "stealth_accumulation": "Many small buys (avoiding detection)",
        "extreme_ratio": "Heavy buying, almost no selling",
        "sybil_pattern": "Suspicious new wallet activity",
        "whale_concentration": "Top buyers hold majority",
        "slow_stealth_accumulation": "Prolonged quiet accumulation",
        "slow_concentration": "Gradual concentration over time",
        "gradual_accumulation": "Steady buy pressure building",
    }

    @staticmethod
    def format_discord_embed(
        alert: Alert,
        cto_score: Optional[CTOScore] = None,
    ) -> dict:
        """
        Format alert as a clean, scannable Discord embed.
        """
        # Determine risk level
        risk_level = AlertFormatter._get_risk_level(cto_score) if cto_score else "MEDIUM"
        color = AlertFormatter.RISK_COLORS.get(risk_level, 0xFFAA00)
        risk_emoji = AlertFormatter.RISK_EMOJI.get(risk_level, "\U0001F7E0")

        # Token display
        if alert.token_name and alert.token_symbol:
            token_display = f"{alert.token_name} (${alert.token_symbol})"
        elif alert.token_symbol:
            token_display = f"${alert.token_symbol}"
        else:
            token_display = f"`{alert.mint[:12]}...`"

        # Build title with risk indicator
        if cto_score:
            title = f"{risk_emoji} {risk_level} RISK - {token_display}"
        else:
            title = f"{risk_emoji} POTENTIAL CTO - {token_display}"

        # Build description with trigger explanation
        trigger_human = alert.trigger_name.replace("_", " ").title()
        trigger_desc = AlertFormatter.TRIGGER_DESCRIPTIONS.get(
            alert.trigger_name,
            alert.trigger_reason
        )

        description = f"**{trigger_human}**\n{trigger_desc}"

        # === FIELDS ===
        fields = []

        # 5-Minute Activity (compact)
        activity_stats = (
            f"\U0001F4B0 **{alert.volume_sol_5m:.1f} SOL** volume\n"
            f"\U0001F6D2 **{alert.buy_count_5m}** buys from **{alert.unique_buyers_5m}** wallets\n"
            f"\U0001F4CA **{AlertFormatter._format_ratio(alert.buy_sell_ratio_5m)}** buy/sell ratio"
        )
        fields.append({
            "name": "\U0001F4CA 5-Minute Activity",
            "value": activity_stats,
            "inline": True,
        })

        # CTO Score breakdown (if available)
        if cto_score and cto_score.total_score > 0:
            score_pct = int(cto_score.total_score * 100)

            # Build score bar
            filled = int(score_pct / 10)
            bar = "\U0001F7E5" * filled + "\U00002B1C" * (10 - filled)

            score_text = f"{bar} **{score_pct}%**\n"

            # Add top contributing factors
            if cto_score.component_scores:
                top_factors = sorted(
                    cto_score.component_scores.items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:3]
                for factor, value in top_factors:
                    if value > 0.1:
                        factor_name = factor.replace("_", " ").title()
                        score_text += f"\u2022 {factor_name}: {value:.0%}\n"

            fields.append({
                "name": "\U0001F3AF CTO Likelihood",
                "value": score_text.strip(),
                "inline": True,
            })

        # Evidence / Red flags
        evidence_lines = []

        # Add specific evidence from trigger
        if "unique_buyers" in alert.trigger_reason.lower():
            ratio = alert.buy_count_5m / max(alert.unique_buyers_5m, 1)
            if ratio > 3:
                evidence_lines.append(f"\U0001F6A9 {ratio:.1f} buys per wallet (coordinated?)")

        if alert.buy_sell_ratio_5m > 10:
            evidence_lines.append(f"\U0001F6A9 {alert.buy_sell_ratio_5m:.0f}x more buys than sells")
        elif alert.buy_sell_ratio_5m == float('inf'):
            evidence_lines.append("\U0001F6A9 All buys, zero sells")

        if alert.unique_buyers_5m <= 5 and alert.volume_sol_5m > 5:
            evidence_lines.append(f"\U0001F6A9 Only {alert.unique_buyers_5m} wallets moved {alert.volume_sol_5m:.1f} SOL")

        # Add CTO evidence
        if cto_score and cto_score.evidence:
            for ev in cto_score.evidence[:2]:
                if ev not in str(evidence_lines):
                    evidence_lines.append(f"\U0001F6A9 {ev}")

        if evidence_lines:
            fields.append({
                "name": "\U0001F50D Why This Was Flagged",
                "value": "\n".join(evidence_lines[:4]),
                "inline": False,
            })

        # Top Buyers with wallet links
        if alert.top_buyers:
            buyer_lines = []
            total_top_volume = 0

            for i, buyer in enumerate(alert.top_buyers[:5]):
                wallet = buyer.get("user_wallet", buyer.get("wallet", ""))
                wallet_short = wallet[:6] + "..." + wallet[-4:] if len(wallet) > 12 else wallet

                volume = buyer.get("total_quote", buyer.get("volume", 0))
                if isinstance(volume, (int, float)):
                    volume_sol = volume / 1e9 if volume > 1e6 else volume
                    total_top_volume += volume_sol

                    # Medal for top 3
                    medal = ["\U0001F947", "\U0001F948", "\U0001F949", "", ""][i]
                    buyer_lines.append(
                        f"{medal} [`{wallet_short}`](https://solscan.io/account/{wallet}) - **{volume_sol:.2f}** SOL"
                    )

            if buyer_lines:
                # Calculate concentration
                if alert.volume_sol_5m > 0:
                    concentration = (total_top_volume / alert.volume_sol_5m) * 100
                    header = f"\U0001F465 Top Buyers ({concentration:.0f}% of volume)"
                else:
                    header = "\U0001F465 Top Buyers"

                fields.append({
                    "name": header,
                    "value": "\n".join(buyer_lines),
                    "inline": False,
                })

        # Cluster Analysis (if wallets are linked)
        if alert.cluster_summary and "cluster" in alert.cluster_summary.lower():
            fields.append({
                "name": "\U0001F517 Wallet Clusters",
                "value": alert.cluster_summary,
                "inline": False,
            })

        # Quick Links - prominent, easy to click
        links = (
            f"[\U0001F50D Birdeye](https://birdeye.so/token/{alert.mint}?chain=solana) \u2022 "
            f"[\U0001F4CA DexScreener](https://dexscreener.com/solana/{alert.mint}) \u2022 "
            f"[\U0001F9FE Solscan](https://solscan.io/token/{alert.mint})"
        )

        fields.append({
            "name": "\U0001F517 Investigate",
            "value": links,
            "inline": False,
        })

        # Degraded warning (if applicable)
        if alert.enrichment_degraded:
            fields.append({
                "name": "\u26A0\uFE0F Limited Analysis",
                "value": "_Helius credit limit reached - some enrichment skipped_",
                "inline": False,
            })

        # Build embed
        embed = {
            "title": title,
            "url": f"https://dexscreener.com/solana/{alert.mint}",  # Makes title clickable
            "description": description,
            "color": color,
            "fields": fields,
            "footer": {
                "text": f"Mint: {alert.mint}"
            },
            "timestamp": (alert.created_at or datetime.utcnow()).isoformat(),
        }

        return {"embeds": [embed]}

    @staticmethod
    def format_telegram(
        alert: Alert,
        cto_score: Optional[CTOScore] = None,
    ) -> str:
        """Format alert as Telegram message (Markdown)."""
        risk_level = AlertFormatter._get_risk_level(cto_score) if cto_score else "MEDIUM"
        risk_emoji = AlertFormatter.RISK_EMOJI.get(risk_level, "\U0001F7E0")

        # Token display
        if alert.token_name and alert.token_symbol:
            token_display = f"{alert.token_name} (${alert.token_symbol})"
        elif alert.token_symbol:
            token_display = f"${alert.token_symbol}"
        else:
            token_display = alert.mint[:12] + "..."

        trigger_human = alert.trigger_name.replace("_", " ").title()

        lines = [
            f"{risk_emoji} *{risk_level} RISK - {token_display}*",
            "",
            f"*{trigger_human}*",
            AlertFormatter.TRIGGER_DESCRIPTIONS.get(alert.trigger_name, alert.trigger_reason),
            "",
            f"\U0001F4B0 *{alert.volume_sol_5m:.1f} SOL* from *{alert.unique_buyers_5m}* wallets",
            f"\U0001F6D2 *{alert.buy_count_5m}* buys | *{alert.buy_sell_ratio_5m:.1f}x* ratio",
        ]

        if cto_score:
            lines.extend([
                "",
                f"\U0001F3AF CTO Score: *{cto_score.total_score:.0%}*",
            ])
            if cto_score.evidence:
                for ev in cto_score.evidence[:2]:
                    lines.append(f"  \u2022 {ev}")

        if alert.top_buyers:
            lines.append("")
            lines.append("*Top Buyers:*")
            for i, buyer in enumerate(alert.top_buyers[:3]):
                wallet = buyer.get("user_wallet", "")[:8]
                volume = buyer.get("total_quote", 0)
                volume_sol = volume / 1e9 if volume > 1e6 else volume
                lines.append(f"  {i+1}. `{wallet}...` - {volume_sol:.2f} SOL")

        lines.extend([
            "",
            f"`{alert.mint}`",
            "",
            f"[Birdeye](https://birdeye.so/token/{alert.mint}) | "
            f"[DexScreener](https://dexscreener.com/solana/{alert.mint})",
        ])

        return "\n".join(lines)

    @staticmethod
    def format_plain(alert: Alert, cto_score: Optional[CTOScore] = None) -> str:
        """Format alert as plain text for logging."""
        token = alert.token_symbol or alert.mint[:8]
        score = f"{cto_score.total_score:.0%}" if cto_score else "N/A"
        return (
            f"[ALERT] {token} | {alert.trigger_name} | "
            f"Vol: {alert.volume_sol_5m:.1f} SOL | Buyers: {alert.unique_buyers_5m} | "
            f"CTO: {score}"
        )

    @staticmethod
    def _format_ratio(ratio: float) -> str:
        """Format buy/sell ratio for display."""
        if ratio == float('inf') or ratio > 1000:
            return "ALL BUYS (no sells)"
        elif ratio > 100:
            return f"{ratio:.0f}x (almost no sells)"
        elif ratio > 10:
            return f"{ratio:.0f}x"
        else:
            return f"{ratio:.1f}x"

    @staticmethod
    def _get_risk_level(score: Optional[CTOScore]) -> str:
        """Determine risk level from CTO score."""
        if not score:
            return "MEDIUM"

        if score.total_score >= 0.8:
            return "CRITICAL"
        elif score.total_score >= 0.6:
            return "HIGH"
        elif score.total_score >= 0.4:
            return "MEDIUM"
        elif score.total_score >= 0.2:
            return "LOW"
        else:
            return "MINIMAL"
