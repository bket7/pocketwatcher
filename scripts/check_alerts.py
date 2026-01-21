"""Quick script to check recent alerts."""
import asyncio
import sys
sys.path.insert(0, "C:\\Users\\Administrator\\Desktop\\Projects\\pocketwatcher")
from storage.postgres_client import PostgresClient


async def main():
    client = PostgresClient()
    await client.connect()

    # First check if columns exist
    cols = await client.pool.fetch("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'alerts'
        ORDER BY ordinal_position
    """)
    print("Alert columns:", [c["column_name"] for c in cols])
    print()

    rows = await client.pool.fetch("""
        SELECT mint, token_name, token_symbol, mcap_sol, venue,
               token_image IS NOT NULL as has_image, created_at
        FROM alerts
        ORDER BY created_at DESC
        LIMIT 10
    """)

    print("Recent alerts:")
    print("-" * 80)
    for r in rows:
        symbol = r["token_symbol"] or r["mint"][:8]
        mcap = f"{r['mcap_sol']:.1f}" if r["mcap_sol"] else "NULL"
        venue = r["venue"] or "NULL"
        img = "YES" if r["has_image"] else "NO"
        print(f"{symbol:12} | mcap: {mcap:>10} | venue: {venue:8} | img: {img} | {r['created_at']}")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
