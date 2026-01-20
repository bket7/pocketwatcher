# Pocketwatcher User Guide

## What is Pocketwatcher?

Pocketwatcher monitors Solana meme coins for **CTO activity** - coordinated buying patterns that suggest insiders or "cabals" are accumulating tokens before a pump.

When suspicious patterns are detected, you get a Discord alert with evidence so you can investigate and decide whether to trade.

---

## Understanding Alerts

### Risk Levels

| Level | Color | What it means |
|-------|-------|---------------|
| **CRITICAL** | Red | Very high confidence of coordinated activity. Multiple red flags. |
| **HIGH** | Orange-Red | Strong signals of insider accumulation. Worth investigating. |
| **MEDIUM** | Orange | Moderate suspicion. Could be organic, could be coordinated. |
| **LOW** | Yellow | Weak signals. Probably organic activity. |
| **MINIMAL** | Green | Very unlikely to be CTO. Normal trading patterns. |

---

## Key Terms Explained

### CTO (Cabal/Team/Organization)

A group of wallets working together to accumulate a token before pumping it. They might be:
- The token creators (dev wallets)
- A coordinated trading group (cabal)
- Insiders with advance knowledge

**Why it matters:** If you spot CTO activity early, you might catch a pump. If you spot it late, you might be exit liquidity.

---

### CTO Score

A 0-100% likelihood that the activity is coordinated rather than organic.

```
🟥🟥🟥🟥🟥🟥🟥⬜⬜⬜ 68%
```

**How it's calculated:**

| Factor | Weight | What it measures |
|--------|--------|------------------|
| **Cluster** | 30% | Are buyers' wallets linked (same funder)? |
| **Concentration** | 25% | Do a few wallets hold most of the buys? |
| **Timing** | 15% | Are buys happening in coordinated bursts? |
| **New Wallet** | 15% | Are buyers freshly-created wallets? |
| **Buy/Sell Ratio** | 15% | Is there heavy buying with no selling? |

---

### Triggers (Why Alerts Fire)

#### Whale Concentration
**What:** A small number of wallets (usually top 3) bought most of the volume.

**Example:** 3 wallets bought 80% of all volume in 5 minutes.

**Why suspicious:** Normal organic buying is spread across many wallets. When a few wallets dominate, they likely know something.

---

#### Extreme Ratio
**What:** Heavy buying with almost no selling.

**Example:** 50 buys, 0 sells in 5 minutes.

**Why suspicious:** In normal trading, some people always sell. When EVERYONE is buying, it's coordinated accumulation before a planned pump.

---

#### Concentrated Accumulation
**What:** Multiple buys from very few wallets.

**Example:** 30 buys from only 4 wallets.

**Why suspicious:** These wallets are splitting buys to avoid detection. Normal traders don't buy 8 times in 5 minutes.

---

#### Stealth Accumulation
**What:** Many small buys designed to fly under the radar.

**Example:** 100 buys averaging 0.2 SOL each.

**Why suspicious:** Cabals often use small buys to accumulate without triggering whale alerts on other tools.

---

#### Sybil Pattern
**What:** High percentage of buyers are brand new wallets.

**Example:** 70% of buyers were created in the last 24 hours.

**Why suspicious:** Cabals create fresh wallets to hide their tracks. Real traders use established wallets.

---

#### Slow Stealth Accumulation
**What:** Same as stealth accumulation but over 1 hour instead of 5 minutes.

**Why it matters:** Some cabals are patient and accumulate slowly to avoid detection.

---

### Wallet Clusters

When we trace where wallets got their SOL, we sometimes find they share the same **funder** - a parent wallet that sent them SOL.

```
🔗 Wallet Clusters
3 wallets in 1 cluster (same funder: 4kPm...)
Cluster bought 39.5 SOL (84% of volume)
```

**What this means:** These 3 wallets are almost certainly controlled by the same person/group. They're pretending to be separate buyers but they're not.

**How we find this:**
1. Look at each buyer wallet
2. Check where they got their SOL (funding transaction)
3. If multiple wallets were funded by the same source = same cluster

---

### Top Buyers

The wallets that bought the most, ranked by volume:

```
🥇 7xKp2R...9fNm - 18.50 SOL
🥈 3mNvQe...kL4x - 12.30 SOL
🥉 9pWr1T...nH7v - 8.75 SOL
```

**Click the wallet address** to see their full history on Solscan.

**What to look for:**
- Did this wallet just get created?
- Does it only trade this one token?
- Did it receive SOL from another buyer?

---

## How to Use Alerts

### When you get an alert:

1. **Check the risk level** - CRITICAL/HIGH are worth immediate attention

2. **Read "Why This Was Flagged"** - This tells you exactly what triggered the alert

3. **Click Birdeye/DexScreener** - Check the chart. Is it already pumping or still early?

4. **Check the clusters** - If buyers are linked, that's a strong CTO signal

5. **Click top buyer wallets** - See if they're fresh wallets or have trading history

### Green flags (probably safe):
- Many unique buyers (10+)
- Normal buy/sell ratio (under 3x)
- No wallet clusters found
- Buyers have trading history

### Red flags (likely CTO):
- Few wallets, high volume
- All buys, no sells
- Wallets funded by same source
- Fresh wallets only
- Buys happening in bursts

---

## Alert Sections Explained

```
🔴 HIGH RISK - TokenName ($SYMBOL)
```
^ Risk level and token info

```
Whale Concentration
Top buyers hold majority
```
^ Which trigger fired and what it means

```
📊 5-Minute Activity
💰 47.3 SOL volume
🛒 34 buys from 6 wallets
📊 ALL BUYS (no sells)
```
^ Raw stats from the last 5 minutes

```
🎯 CTO Likelihood
🟥🟥🟥🟥🟥🟥🟥⬜⬜⬜ 68%
• Cluster: 85%
• Concentration: 72%
```
^ Overall score and top contributing factors

```
🔍 Why This Was Flagged
🚩 All buys, zero sells
🚩 Only 6 wallets moved 47.3 SOL
```
^ Specific evidence for this alert

```
👥 Top Buyers (89% of volume)
🥇 7xKp2R...9fNm - 18.50 SOL
```
^ Who bought the most (clickable links)

```
🔗 Wallet Clusters
3 wallets in 1 cluster
```
^ If wallets are connected

```
🔗 Investigate
[Birdeye] • [DexScreener] • [Solscan]
```
^ One-click links to research

---

## FAQ

**Q: How fast are alerts?**
A: Alerts fire within seconds of detecting suspicious patterns. We stream transactions in real-time.

**Q: Will I get spammed with alerts?**
A: No. Triggers are tuned to only fire on genuinely suspicious activity. You might get 5-20 alerts per day during active markets.

**Q: What if I miss a pump?**
A: The alert shows you early accumulation. The pump usually happens later. You have time to research.

**Q: Are all alerts guaranteed CTO?**
A: No. Some will be false positives (organic whales, lucky timing). Use the evidence to make your own decision.

**Q: Can cabals avoid detection?**
A: Sophisticated cabals might, but most don't. We catch the common patterns.

---

## Quick Reference

| Term | Meaning |
|------|---------|
| CTO | Coordinated insider buying |
| Cluster | Wallets with same funder |
| Concentration | % held by top wallets |
| Sybil | Fake/new wallets |
| Stealth | Small buys to avoid detection |
| Ratio | Buys divided by sells |
| Funder | Wallet that sent SOL |
| HOT token | Token we're actively monitoring |
