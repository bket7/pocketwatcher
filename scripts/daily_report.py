"""
Daily Report Script

Generates a report comparing alert-time market caps with current values.
Uses GMGN to fetch current token prices.
"""

import argparse
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import asyncpg

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings
from scripts.gmgn_client import GMGNClient, TokenData


async def get_todays_alerts(
    conn: asyncpg.Connection,
    date: Optional[datetime] = None
) -> List[dict]:
    """
    Get alerts for a specific date from PostgreSQL.

    Args:
        conn: PostgreSQL connection
        date: Date to query (default: today)

    Returns:
        List of alert dicts with price data
    """
    if date is None:
        date = datetime.utcnow().date()

    start = datetime.combine(date, datetime.min.time())
    end = datetime.combine(date, datetime.max.time())

    rows = await conn.fetch("""
        SELECT
            id,
            mint,
            token_name,
            token_symbol,
            trigger_name,
            trigger_reason,
            price_sol,
            mcap_sol,
            token_supply,
            volume_sol_5m,
            unique_buyers_5m,
            created_at
        FROM alerts
        WHERE created_at >= $1 AND created_at <= $2
        ORDER BY created_at ASC
    """, start, end)

    return [dict(row) for row in rows]


def format_sol(value: Optional[float], decimals: int = 2) -> str:
    """Format SOL value for display."""
    if value is None:
        return "N/A"
    if value >= 1_000_000:
        return f"{value/1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value/1_000:.1f}K"
    return f"{value:.{decimals}f}"


def format_usd(value: Optional[float]) -> str:
    """Format USD value for display."""
    if value is None:
        return "N/A"
    if value >= 1_000_000:
        return f"${value/1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value/1_000:.1f}K"
    return f"${value:.2f}"


def format_pct(value: Optional[float]) -> str:
    """Format percentage for display."""
    if value is None:
        return "N/A"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.0%}"


async def generate_report(date: Optional[datetime] = None, skip_gmgn: bool = False):
    """
    Generate daily report.

    Args:
        date: Date to report on (default: today)
        skip_gmgn: Skip GMGN fetching (for testing)
    """
    if date is None:
        date = datetime.utcnow().date()

    print(f"\n{'='*60}")
    print(f" Pocketwatcher Daily Report ({date})")
    print(f"{'='*60}\n")

    # Connect to database
    conn = await asyncpg.connect(settings.postgres_url)

    try:
        # Get alerts for the day
        alerts = await get_todays_alerts(conn, date)

        if not alerts:
            print("No alerts found for this date.\n")
            return

        print(f"Total alerts: {len(alerts)}")

        # Get unique tokens
        unique_mints = list(set(a["mint"] for a in alerts))
        print(f"Unique tokens: {len(unique_mints)}\n")

        # Fetch current prices from GMGN (if not skipped)
        current_prices: dict[str, TokenData] = {}

        if not skip_gmgn:
            print("Fetching current prices from GMGN...")
            try:
                async with GMGNClient() as client:
                    current_prices = await client.get_tokens_batch(
                        unique_mints,
                        delay=1.5  # Rate limit
                    )
                    success_count = sum(1 for t in current_prices.values() if t.success)
                    print(f"  Fetched {success_count}/{len(unique_mints)} tokens\n")
            except Exception as e:
                print(f"  Warning: GMGN fetch failed: {e}")
                print("  Continuing without current prices...\n")

        # Calculate performance metrics
        performances = []

        for alert in alerts:
            mint = alert["mint"]
            alert_mcap = alert["mcap_sol"]

            current = current_prices.get(mint)
            current_mcap = None
            gain_pct = None

            if current and current.success and current.market_cap_usd:
                # Convert USD mcap to SOL estimate (rough)
                # For now, just store USD mcap
                current_mcap = current.market_cap_usd

            if alert_mcap and current_mcap:
                # Can't directly compare SOL mcap to USD mcap
                # Would need SOL price at alert time and now
                pass

            performances.append({
                "alert": alert,
                "current": current,
                "current_mcap_usd": current_mcap,
                "gain_pct": gain_pct,
            })

        # Print summary table
        print("-" * 80)
        print(f"{'Token':<12} {'Symbol':<8} {'Trigger':<15} {'Alert MCap':<12} {'Current MCap':<14} {'Gain':<8}")
        print("-" * 80)

        for perf in performances:
            alert = perf["alert"]
            current = perf["current"]

            token_short = alert["mint"][:8] + ".."
            symbol = alert["token_symbol"] or "???"
            if symbol and len(symbol) > 7:
                symbol = symbol[:7]

            trigger = alert["trigger_name"] or "unknown"
            if len(trigger) > 14:
                trigger = trigger[:14]

            alert_mcap = format_sol(alert["mcap_sol"]) + " SOL" if alert["mcap_sol"] else "N/A"
            current_mcap = format_usd(perf["current_mcap_usd"]) if perf["current_mcap_usd"] else "N/A"
            gain = format_pct(perf["gain_pct"]) if perf["gain_pct"] is not None else "-"

            print(f"{token_short:<12} {symbol:<8} {trigger:<15} {alert_mcap:<12} {current_mcap:<14} {gain:<8}")

        print("-" * 80)

        # Stats summary
        alerts_with_mcap = [a for a in alerts if a["mcap_sol"] is not None]
        if alerts_with_mcap:
            avg_alert_mcap = sum(a["mcap_sol"] for a in alerts_with_mcap) / len(alerts_with_mcap)
            print(f"\nAverage alert mcap: {format_sol(avg_alert_mcap)} SOL")

        # Trigger breakdown
        trigger_counts = {}
        for alert in alerts:
            trigger = alert["trigger_name"] or "unknown"
            trigger_counts[trigger] = trigger_counts.get(trigger, 0) + 1

        print("\nTrigger breakdown:")
        for trigger, count in sorted(trigger_counts.items(), key=lambda x: -x[1]):
            print(f"  {trigger}: {count}")

        print()

    finally:
        await conn.close()


def parse_date(date_str: str) -> datetime:
    """Parse date string."""
    if date_str.lower() == "today":
        return datetime.utcnow().date()
    if date_str.lower() == "yesterday":
        return (datetime.utcnow() - timedelta(days=1)).date()

    # Try various formats
    for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"]:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue

    raise ValueError(f"Cannot parse date: {date_str}")


async def main():
    parser = argparse.ArgumentParser(description="Generate Pocketwatcher daily report")
    parser.add_argument(
        "--date",
        type=str,
        default="today",
        help="Date to report on (YYYY-MM-DD, 'today', or 'yesterday')"
    )
    parser.add_argument(
        "--skip-gmgn",
        action="store_true",
        help="Skip GMGN price fetching"
    )

    args = parser.parse_args()

    try:
        report_date = parse_date(args.date)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    await generate_report(date=report_date, skip_gmgn=args.skip_gmgn)


if __name__ == "__main__":
    asyncio.run(main())
