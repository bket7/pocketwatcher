"""Investigate why alert counts vary by date."""

import asyncio
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import settings


async def investigate():
    conn = await asyncpg.connect(settings.postgres_url)

    print('=== ALERTS BY DATE ===')
    rows = await conn.fetch('''
        SELECT
            DATE(created_at) as date,
            COUNT(*) as total,
            COUNT(DISTINCT trigger_name) as triggers_used,
            MIN(created_at) as first_alert,
            MAX(created_at) as last_alert
        FROM alerts
        WHERE created_at >= NOW() - INTERVAL '7 days'
        GROUP BY DATE(created_at)
        ORDER BY date DESC
    ''')
    for r in rows:
        diff = (r['last_alert'] - r['first_alert']).total_seconds() / 3600
        print(f"{r['date']}: {r['total']:>5} alerts | {r['triggers_used']} triggers | span: {diff:.1f}h")

    print()
    print('=== SWAP EVENTS BY DATE ===')
    rows = await conn.fetch('''
        SELECT
            DATE(to_timestamp(block_time)) as date,
            COUNT(*) as swaps
        FROM swap_events
        WHERE block_time >= EXTRACT(EPOCH FROM NOW() - INTERVAL '7 days')
        GROUP BY DATE(to_timestamp(block_time))
        ORDER BY date DESC
    ''')
    for r in rows:
        print(f"{r['date']}: {r['swaps']:>7} swaps")

    print()
    print('=== TRIGGERS BREAKDOWN BY DATE ===')
    rows = await conn.fetch('''
        SELECT
            DATE(created_at) as date,
            trigger_name,
            COUNT(*) as count
        FROM alerts
        WHERE created_at >= NOW() - INTERVAL '5 days'
        GROUP BY DATE(created_at), trigger_name
        ORDER BY date DESC, count DESC
    ''')
    current_date = None
    for r in rows:
        if r['date'] != current_date:
            print(f"\n{r['date']}:")
            current_date = r['date']
        print(f"  {r['trigger_name']:<30} {r['count']:>5}")

    # Check if there were config changes or restarts
    print()
    print('=== CHECKING FOR GAPS ===')
    rows = await conn.fetch('''
        SELECT
            created_at,
            LEAD(created_at) OVER (ORDER BY created_at) as next_alert,
            EXTRACT(EPOCH FROM (LEAD(created_at) OVER (ORDER BY created_at) - created_at)) / 3600 as gap_hours
        FROM alerts
        WHERE created_at >= NOW() - INTERVAL '5 days'
        ORDER BY created_at
    ''')

    big_gaps = [(r['created_at'], r['next_alert'], r['gap_hours']) for r in rows if r['gap_hours'] and r['gap_hours'] > 1]
    if big_gaps:
        print(f"Found {len(big_gaps)} gaps > 1 hour:")
        for start, end, hours in big_gaps[:10]:
            print(f"  {start} -> {end} ({hours:.1f}h gap)")
    else:
        print("No significant gaps found")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(investigate())
