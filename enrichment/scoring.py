"""CTO (Cabal/Team/Organization) likelihood scoring."""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from .clustering import Cluster, WalletClusterer
from detection.counters import TokenStats

logger = logging.getLogger(__name__)


@dataclass
class CTOScore:
    """CTO likelihood score with breakdown."""
    total_score: float  # 0.0 to 1.0
    confidence: float   # How confident we are in the score

    # Component scores (each 0.0 to 1.0)
    concentration_score: float = 0.0
    cluster_score: float = 0.0
    timing_score: float = 0.0
    new_wallet_score: float = 0.0
    ratio_score: float = 0.0

    # Evidence
    evidence: List[str] = None

    def __post_init__(self):
        if self.evidence is None:
            self.evidence = []


class CTOScorer:
    """
    Scores CTO (Cabal/Team/Organization) likelihood for a token.

    Components:
    - Concentration: How concentrated is buying among top wallets?
    - Clustering: Are top buyers in the same cluster (linked wallets)?
    - Timing: Are buys suspiciously synchronized?
    - New wallets: High percentage of newly-seen wallets?
    - Ratio: Extreme buy/sell ratio (all buying, no selling)?
    """

    # Weights for each component
    WEIGHTS = {
        "concentration": 0.25,
        "cluster": 0.30,
        "timing": 0.15,
        "new_wallet": 0.15,
        "ratio": 0.15,
    }

    def __init__(self, clusterer: WalletClusterer):
        self.clusterer = clusterer

    def score_token(
        self,
        stats: TokenStats,
        top_buyers: List[Dict],
    ) -> CTOScore:
        """
        Calculate CTO score for a token.

        Args:
            stats: Token activity statistics
            top_buyers: List of {wallet, volume, buy_count} dicts
        """
        evidence = []

        # === Concentration Score ===
        concentration_score = self._score_concentration(stats, evidence)

        # === Cluster Score ===
        cluster_score = self._score_clustering(top_buyers, evidence)

        # === Timing Score ===
        # Note: Would need per-tx timestamps for proper timing analysis
        # Simplified: use buy count vs unique buyers as proxy
        timing_score = self._score_timing(stats, evidence)

        # === New Wallet Score ===
        new_wallet_score = self._score_new_wallets(stats, evidence)

        # === Ratio Score ===
        ratio_score = self._score_ratio(stats, evidence)

        # Calculate weighted total
        total = (
            concentration_score * self.WEIGHTS["concentration"] +
            cluster_score * self.WEIGHTS["cluster"] +
            timing_score * self.WEIGHTS["timing"] +
            new_wallet_score * self.WEIGHTS["new_wallet"] +
            ratio_score * self.WEIGHTS["ratio"]
        )

        # Confidence based on data quality
        confidence = self._calculate_confidence(stats, top_buyers)

        return CTOScore(
            total_score=total,
            confidence=confidence,
            concentration_score=concentration_score,
            cluster_score=cluster_score,
            timing_score=timing_score,
            new_wallet_score=new_wallet_score,
            ratio_score=ratio_score,
            evidence=evidence,
        )

    def _score_concentration(
        self,
        stats: TokenStats,
        evidence: List[str]
    ) -> float:
        """Score based on top buyer concentration."""
        top_3_share = stats.top_3_volume_share

        if top_3_share >= 0.8:
            evidence.append(f"Very high concentration: top 3 = {top_3_share:.0%}")
            return 1.0
        elif top_3_share >= 0.6:
            evidence.append(f"High concentration: top 3 = {top_3_share:.0%}")
            return 0.8
        elif top_3_share >= 0.4:
            return 0.5
        elif top_3_share >= 0.2:
            return 0.2
        else:
            return 0.0

    def _score_clustering(
        self,
        top_buyers: List[Dict],
        evidence: List[str]
    ) -> float:
        """Score based on cluster membership of top buyers."""
        if not top_buyers:
            return 0.0

        wallets = [b.get("wallet") or b.get("user_wallet") for b in top_buyers if b]
        wallets = [w for w in wallets if w]

        if not wallets:
            return 0.0

        # Get clusters for these wallets
        clusters = self.clusterer.get_cluster_for_wallets(wallets)

        if not clusters:
            return 0.0

        # Calculate what % of wallets are in multi-member clusters
        large_cluster_wallets = sum(c.size for c in clusters if c.size >= 2)
        cluster_pct = large_cluster_wallets / len(wallets) if wallets else 0

        if cluster_pct >= 0.5:
            max_cluster = max(clusters, key=lambda c: c.size)
            evidence.append(
                f"High clustering: {cluster_pct:.0%} in linked wallets, "
                f"largest cluster = {max_cluster.size}"
            )
            return min(1.0, cluster_pct + 0.2)
        elif cluster_pct >= 0.2:
            evidence.append(f"Some clustering: {cluster_pct:.0%} in linked wallets")
            return cluster_pct + 0.1

        return 0.0

    def _score_timing(
        self,
        stats: TokenStats,
        evidence: List[str]
    ) -> float:
        """Score based on timing patterns (simplified)."""
        # Use buy_count / unique_buyers as proxy for coordination
        # High ratio = many buys per buyer = possibly automated/coordinated

        if stats.unique_buyers == 0:
            return 0.0

        buys_per_buyer = stats.buy_count / stats.unique_buyers

        if buys_per_buyer >= 10:
            evidence.append(f"High buy frequency: {buys_per_buyer:.1f} buys/wallet")
            return 1.0
        elif buys_per_buyer >= 5:
            evidence.append(f"Elevated buy frequency: {buys_per_buyer:.1f} buys/wallet")
            return 0.7
        elif buys_per_buyer >= 3:
            return 0.4
        elif buys_per_buyer >= 2:
            return 0.2
        else:
            return 0.0

    def _score_new_wallets(
        self,
        stats: TokenStats,
        evidence: List[str]
    ) -> float:
        """Score based on new wallet percentage."""
        new_pct = stats.new_wallet_pct

        if new_pct >= 0.7:
            evidence.append(f"Very high new wallet %: {new_pct:.0%}")
            return 1.0
        elif new_pct >= 0.5:
            evidence.append(f"High new wallet %: {new_pct:.0%}")
            return 0.7
        elif new_pct >= 0.3:
            return 0.4
        else:
            return 0.0

    def _score_ratio(
        self,
        stats: TokenStats,
        evidence: List[str]
    ) -> float:
        """Score based on buy/sell ratio."""
        ratio = stats.buy_sell_ratio

        if ratio == float('inf') or ratio >= 20:
            evidence.append(f"Extreme buy ratio: {ratio:.1f}x" if ratio != float('inf') else "All buys, no sells")
            return 1.0
        elif ratio >= 10:
            evidence.append(f"Very high buy ratio: {ratio:.1f}x")
            return 0.8
        elif ratio >= 5:
            return 0.5
        elif ratio >= 3:
            return 0.3
        else:
            return 0.0

    def _calculate_confidence(
        self,
        stats: TokenStats,
        top_buyers: List[Dict]
    ) -> float:
        """Calculate confidence in the score based on data quality."""
        confidence = 1.0

        # Low sample size reduces confidence
        if stats.buy_count < 5:
            confidence -= 0.3
        elif stats.buy_count < 10:
            confidence -= 0.2
        elif stats.buy_count < 20:
            confidence -= 0.1

        # Few top buyers reduces confidence
        if len(top_buyers) < 3:
            confidence -= 0.2
        elif len(top_buyers) < 5:
            confidence -= 0.1

        # Low volume reduces confidence
        if stats.volume_sol < 1.0:
            confidence -= 0.2
        elif stats.volume_sol < 5.0:
            confidence -= 0.1

        return max(0.1, confidence)

    def get_risk_level(self, score: CTOScore) -> str:
        """Get human-readable risk level."""
        if score.total_score >= 0.7:
            return "HIGH"
        elif score.total_score >= 0.4:
            return "MEDIUM"
        elif score.total_score >= 0.2:
            return "LOW"
        else:
            return "MINIMAL"

    def format_score_summary(self, score: CTOScore) -> str:
        """Format score for alert display."""
        risk = self.get_risk_level(score)

        summary = f"CTO Risk: {risk} ({score.total_score:.0%})"

        if score.evidence:
            summary += "\n  " + "\n  ".join(score.evidence[:3])

        return summary
