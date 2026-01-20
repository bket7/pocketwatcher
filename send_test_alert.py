"""Send a sample alert to preview the new format."""
import asyncio
import httpx

WEBHOOK_URL = "https://discordapp.com/api/webhooks/1463080427349606563/evMWpaQciQiDoC4B4qt61RBc6AUeuEC5kWfkQ36QHiE9lWpNekgiq1Ph2tY3CQXOckVa"

# Sample realistic alert
sample_embed = {
    "embeds": [{
        "title": "\U0001F534 HIGH RISK - ShadowCat ($SCAT)",
        "description": "**Whale Concentration**\nTop buyers hold majority",
        "color": 0xFF4400,
        "fields": [
            {
                "name": "\U0001F4CA 5-Minute Activity",
                "value": "\U0001F4B0 **47.3 SOL** volume\n\U0001F6D2 **34** buys from **6** wallets\n\U0001F4CA **inf** buy/sell ratio",
                "inline": True
            },
            {
                "name": "\U0001F3AF CTO Likelihood",
                "value": "\U0001F7E5\U0001F7E5\U0001F7E5\U0001F7E5\U0001F7E5\U0001F7E5\U0001F7E5\u2B1C\u2B1C\u2B1C **68%**\n\u2022 Cluster: 85%\n\u2022 Concentration: 72%\n\u2022 Timing: 45%",
                "inline": True
            },
            {
                "name": "\U0001F50D Why This Was Flagged",
                "value": "\U0001F6A9 All buys, zero sells\n\U0001F6A9 Only 6 wallets moved 47.3 SOL\n\U0001F6A9 5.7 buys per wallet (coordinated?)\n\U0001F6A9 3 wallets share same funder",
                "inline": False
            },
            {
                "name": "\U0001F465 Top Buyers (89% of volume)",
                "value": "\U0001F947 [`7xKp2R...9fNm`](https://solscan.io/account/7xKp2R9fNm) - **18.50** SOL\n\U0001F948 [`3mNvQe...kL4x`](https://solscan.io/account/3mNvQekL4x) - **12.30** SOL\n\U0001F949 [`9pWr1T...nH7v`](https://solscan.io/account/9pWr1TnH7v) - **8.75** SOL\n [`5vBn8K...jR2m`](https://solscan.io/account/5vBn8KjR2m) - **2.40** SOL",
                "inline": False
            },
            {
                "name": "\U0001F517 Wallet Clusters",
                "value": "**3 wallets** in 1 cluster (same funder: `4kPm...`)\nCluster bought **39.5 SOL** (84% of volume)",
                "inline": False
            },
            {
                "name": "\U0001F517 Investigate",
                "value": "[\U0001F50D Birdeye](https://birdeye.so/token/7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr?chain=solana) \u2022 [\U0001F4CA DexScreener](https://dexscreener.com/solana/7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr) \u2022 [\U0001F9FE Solscan](https://solscan.io/token/7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr)",
                "inline": False
            }
        ],
        "footer": {"text": "Mint: 7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"},
        "timestamp": "2026-01-20T04:15:00.000Z"
    }]
}

async def send():
    async with httpx.AsyncClient() as client:
        resp = await client.post(WEBHOOK_URL, json=sample_embed)
        print(f"Sent! Status: {resp.status_code}")

asyncio.run(send())
