"""
Backtest Script - Check if alerted tokens went up

Uses GMGN as primary source, DexScreener as fallback.
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg
import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import settings
from scripts.gmgn_client import TokenPriceClient


async def get_sol_price() -> float:
    """Get current SOL/USD price from CoinGecko."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "solana", "vs_currencies": "usd"}
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("solana", {}).get("usd", 200)
    return 200  # fallback


async def run_backtest(days: int = 30, limit: int = None):
    """
    Run backtest on recent alerts.

    Args:
        days: How many days back to look
        limit: Max alerts to check (None = all)
    """
    print(f"\n{'='*70}")
    print(f" Pocketwatcher Backtest - Last {days} days")
    print(f"{'='*70}\n")

    # Get SOL price
    sol_price = await get_sol_price()
    print(f"Current SOL price: ${sol_price:.2f}\n")

    # Connect to DB
    conn = await asyncpg.connect(settings.postgres_url)

    try:
        # Get recent alerts with mcap
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        if limit:
            rows = await conn.fetch("""
                SELECT
                    id, mint, token_symbol, token_name, trigger_name,
                    mcap_sol, price_sol, volume_sol_5m, created_at
                FROM alerts
                WHERE created_at >= $1 AND mcap_sol IS NOT NULL AND mcap_sol > 0
                ORDER BY created_at DESC
                LIMIT $2
            """, cutoff, limit)
        else:
            rows = await conn.fetch("""
                SELECT
                    id, mint, token_symbol, token_name, trigger_name,
                    mcap_sol, price_sol, volume_sol_5m, created_at
                FROM alerts
                WHERE created_at >= $1 AND mcap_sol IS NOT NULL AND mcap_sol > 0
                ORDER BY created_at DESC
            """, cutoff)

        print(f"Found {len(rows)} alerts with mcap data\n")

        if not rows:
            print("No alerts to backtest.")
            return

        # Get unique mints
        unique_mints = list(set(row["mint"] for row in rows))
        print(f"Unique tokens: {len(unique_mints)}")

        # Fetch current prices using TokenPriceClient (GMGN + DexScreener)
        print("Fetching current prices...")
        async with TokenPriceClient() as client:
            current_prices = await client.get_tokens_batch(unique_mints, delay=0.3)
            print(f"Source stats: {client.stats}\n")

        # Build results
        results = []
        for row in rows:
            mint = row["mint"]
            current = current_prices.get(mint)

            alert_mcap_usd = row["mcap_sol"] * sol_price if row["mcap_sol"] else None
            current_mcap_usd = current.market_cap_usd if current and current.success else None

            gain_pct = None
            if alert_mcap_usd and current_mcap_usd and alert_mcap_usd > 0:
                gain_pct = (current_mcap_usd - alert_mcap_usd) / alert_mcap_usd

            results.append({
                "mint": mint,
                "symbol": row["token_symbol"] or (current.symbol if current and current.success else "???"),
                "trigger": row["trigger_name"],
                "alert_mcap_usd": alert_mcap_usd,
                "current_mcap_usd": current_mcap_usd,
                "gain_pct": gain_pct,
                "created_at": row["created_at"],
                "volume_sol": row["volume_sol_5m"],
                "source": current.source if current else "N/A",
            })

        # Print results
        print(f"{'-'*100}")
        print(f"{'Symbol':<10} {'Trigger':<20} {'Alert MCap':<12} {'Current MCap':<12} {'Gain':<10} {'Age':<8} {'Source':<10}")
        print(f"{'-'*100}")

        winners = 0
        losers = 0
        total_gain = 0
        valid_count = 0

        for r in results:
            symbol = (r["symbol"] or "???")[:9]
            trigger = (r["trigger"] or "???")[:19]

            alert_mcap = f"${r['alert_mcap_usd']/1000:.0f}K" if r['alert_mcap_usd'] and r['alert_mcap_usd'] >= 1000 else \
                        f"${r['alert_mcap_usd']:.0f}" if r['alert_mcap_usd'] else "N/A"
            if r['alert_mcap_usd'] and r['alert_mcap_usd'] >= 1_000_000:
                alert_mcap = f"${r['alert_mcap_usd']/1_000_000:.1f}M"

            current_mcap = f"${r['current_mcap_usd']/1000:.0f}K" if r['current_mcap_usd'] and r['current_mcap_usd'] >= 1000 else \
                          f"${r['current_mcap_usd']:.0f}" if r['current_mcap_usd'] else "DEAD"
            if r['current_mcap_usd'] and r['current_mcap_usd'] >= 1_000_000:
                current_mcap = f"${r['current_mcap_usd']/1_000_000:.1f}M"

            if r['gain_pct'] is not None:
                gain = f"{r['gain_pct']:+.0%}"
                if r['gain_pct'] > 0:
                    winners += 1
                else:
                    losers += 1
                total_gain += r['gain_pct']
                valid_count += 1
            else:
                gain = "N/A"

            age = datetime.now(timezone.utc) - r['created_at'].replace(tzinfo=timezone.utc)
            age_str = f"{age.total_seconds()/3600:.1f}h"

            print(f"{symbol:<10} {trigger:<20} {alert_mcap:<12} {current_mcap:<12} {gain:<10} {age_str:<8} {r['source']:<10}")

        print(f"{'-'*100}")

        # Summary stats
        print(f"\n{'='*50}")
        print(f" SUMMARY")
        print(f"{'='*50}")
        print(f"Total alerts checked: {len(results)}")
        print(f"Unique tokens: {len(unique_mints)}")
        print(f"With valid price data: {valid_count}")
        if valid_count > 0:
            print(f"Winners (up): {winners} ({winners/valid_count:.0%})")
            print(f"Losers (down): {losers} ({losers/valid_count:.0%})")
            print(f"Average gain: {total_gain/valid_count:+.0%}")

            # Best and worst
            valid_results = [r for r in results if r['gain_pct'] is not None]
            if valid_results:
                best = max(valid_results, key=lambda x: x['gain_pct'])
                worst = min(valid_results, key=lambda x: x['gain_pct'])
                print(f"\nBest: {best['symbol']} {best['gain_pct']:+.0%}")
                print(f"Worst: {worst['symbol']} {worst['gain_pct']:+.0%}")

            # Breakdown by trigger
            print(f"\n{'='*50}")
            print(f" BY TRIGGER")
            print(f"{'='*50}")
            trigger_stats = {}
            for r in valid_results:
                trigger = r["trigger"] or "unknown"
                if trigger not in trigger_stats:
                    trigger_stats[trigger] = {"wins": 0, "losses": 0, "total_gain": 0}
                if r['gain_pct'] > 0:
                    trigger_stats[trigger]["wins"] += 1
                else:
                    trigger_stats[trigger]["losses"] += 1
                trigger_stats[trigger]["total_gain"] += r['gain_pct']

            for trigger, stats in sorted(trigger_stats.items(), key=lambda x: -(x[1]["wins"] + x[1]["losses"])):
                total = stats["wins"] + stats["losses"]
                win_rate = stats["wins"] / total if total > 0 else 0
                avg_gain = stats["total_gain"] / total if total > 0 else 0
                print(f"{trigger:<25} {total:>3} alerts | {win_rate:>5.0%} win | {avg_gain:>+6.0%} avg")

        print()

    finally:
        await conn.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Backtest pocketwatcher alerts")
    parser.add_argument("--days", type=int, default=30, help="Days to look back (default: 30)")
    parser.add_argument("--limit", type=int, default=None, help="Max alerts to check (default: all)")
    args = parser.parse_args()

    asyncio.run(run_backtest(days=args.days, limit=args.limit))
