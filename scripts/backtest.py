"""
Backtest Script - Check if alerted tokens went up

Fetches current prices from DexScreener and compares to alert-time mcap.
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

import asyncpg
import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import settings


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


async def get_dexscreener_price(mint: str) -> dict:
    """Get current price data from DexScreener."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"https://api.dexscreener.com/latest/dex/tokens/{mint}")
            if resp.status_code == 200:
                data = resp.json()
                pairs = data.get("pairs", [])
                if pairs:
                    # Get the most liquid pair
                    best = max(pairs, key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0))
                    return {
                        "price_usd": float(best.get("priceUsd", 0) or 0),
                        "mcap_usd": float(best.get("fdv", 0) or 0),  # fdv = fully diluted valuation
                        "liquidity_usd": float(best.get("liquidity", {}).get("usd", 0) or 0),
                        "symbol": best.get("baseToken", {}).get("symbol", "???"),
                    }
        except Exception as e:
            print(f"  Error fetching {mint[:8]}: {e}")
    return None


async def run_backtest(days: int = 3, limit: int = 50):
    """
    Run backtest on recent alerts.

    Args:
        days: How many days back to look
        limit: Max alerts to check
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
        cutoff = datetime.utcnow() - timedelta(days=days)
        rows = await conn.fetch("""
            SELECT
                id, mint, token_symbol, token_name, trigger_name,
                mcap_sol, price_sol, volume_sol_5m, created_at
            FROM alerts
            WHERE created_at >= $1 AND mcap_sol IS NOT NULL AND mcap_sol > 0
            ORDER BY created_at DESC
            LIMIT $2
        """, cutoff, limit)

        print(f"Found {len(rows)} alerts with mcap data\n")

        if not rows:
            print("No alerts to backtest.")
            return

        # Fetch current prices
        results = []
        print("Fetching current prices from DexScreener...")

        for i, row in enumerate(rows):
            mint = row["mint"]
            current = await get_dexscreener_price(mint)

            alert_mcap_usd = row["mcap_sol"] * sol_price if row["mcap_sol"] else None
            current_mcap_usd = current["mcap_usd"] if current else None

            gain_pct = None
            if alert_mcap_usd and current_mcap_usd and alert_mcap_usd > 0:
                gain_pct = (current_mcap_usd - alert_mcap_usd) / alert_mcap_usd

            results.append({
                "mint": mint,
                "symbol": row["token_symbol"] or (current["symbol"] if current else "???"),
                "trigger": row["trigger_name"],
                "alert_mcap_usd": alert_mcap_usd,
                "current_mcap_usd": current_mcap_usd,
                "gain_pct": gain_pct,
                "created_at": row["created_at"],
                "volume_sol": row["volume_sol_5m"],
            })

            # Rate limit
            if i < len(rows) - 1:
                await asyncio.sleep(0.3)

        # Print results
        print(f"\n{'-'*90}")
        print(f"{'Symbol':<10} {'Trigger':<20} {'Alert MCap':<12} {'Current MCap':<12} {'Gain':<10} {'Age':<10}")
        print(f"{'-'*90}")

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

            age = datetime.utcnow() - r['created_at'].replace(tzinfo=None)
            age_str = f"{age.total_seconds()/3600:.1f}h"

            print(f"{symbol:<10} {trigger:<20} {alert_mcap:<12} {current_mcap:<12} {gain:<10} {age_str:<10}")

        print(f"{'-'*90}")

        # Summary stats
        print(f"\n{'='*50}")
        print(f" SUMMARY")
        print(f"{'='*50}")
        print(f"Total alerts checked: {len(results)}")
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

        print()

    finally:
        await conn.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Backtest pocketwatcher alerts")
    parser.add_argument("--days", type=int, default=3, help="Days to look back")
    parser.add_argument("--limit", type=int, default=50, help="Max alerts to check")
    args = parser.parse_args()

    asyncio.run(run_backtest(days=args.days, limit=args.limit))
