"""Tests for enrichment module."""

import pytest
from enrichment.clustering import UnionFind, WalletClusterer, Cluster
from enrichment.scoring import CTOScorer, CTOScore
from detection.counters import TokenStats
from unittest.mock import MagicMock


class TestUnionFind:
    """Tests for UnionFind data structure."""

    def test_find_creates_set(self):
        """Test find creates a new set for unknown element."""
        uf = UnionFind()
        root = uf.find("wallet_a")
        assert root == "wallet_a"
        assert uf.parent["wallet_a"] == "wallet_a"

    def test_union_links_sets(self):
        """Test union links two sets together."""
        uf = UnionFind()
        uf.find("wallet_a")
        uf.find("wallet_b")

        uf.union("wallet_a", "wallet_b")

        assert uf.connected("wallet_a", "wallet_b")

    def test_path_compression(self):
        """Test path compression optimizes find."""
        uf = UnionFind()
        uf.union("a", "b")
        uf.union("b", "c")
        uf.union("c", "d")

        # After find, all should point to same root
        root = uf.find("d")
        assert uf.find("a") == root
        assert uf.find("b") == root
        assert uf.find("c") == root

    def test_get_all_clusters(self):
        """Test getting all clusters."""
        uf = UnionFind()
        uf.union("a", "b")
        uf.union("c", "d")
        uf.find("e")  # Singleton

        clusters = uf.get_all_clusters()

        assert len(clusters) == 3  # Two pairs + one singleton
        # Find the cluster with a and b
        for root, members in clusters.items():
            if "a" in members:
                assert "b" in members
                assert len(members) == 2


class TestWalletClusterer:
    """Tests for WalletClusterer."""

    def setup_method(self):
        self.mock_postgres = MagicMock()
        self.clusterer = WalletClusterer(self.mock_postgres)

    def test_add_wallet(self):
        """Test adding a wallet."""
        self.clusterer.add_wallet("wallet_a", volume_sol=5.0, buy_count=3)

        cluster = self.clusterer.get_cluster("wallet_a")
        assert "wallet_a" in cluster.members
        assert cluster.total_volume_sol == 5.0
        assert cluster.total_buys == 3

    def test_link_wallets(self):
        """Test linking wallets."""
        self.clusterer.add_wallet("wallet_a", volume_sol=5.0)
        self.clusterer.add_wallet("wallet_b", volume_sol=3.0)
        self.clusterer.link_wallets("wallet_a", "wallet_b")

        cluster = self.clusterer.get_cluster("wallet_a")
        assert "wallet_a" in cluster.members
        assert "wallet_b" in cluster.members
        assert cluster.size == 2
        assert cluster.total_volume_sol == 8.0

    def test_generate_summary(self):
        """Test generating cluster summary."""
        self.clusterer.add_wallet("a", volume_sol=5.0)
        self.clusterer.add_wallet("b", volume_sol=3.0)
        self.clusterer.link_wallets("a", "b")
        self.clusterer.add_wallet("c", volume_sol=2.0)

        summary = self.clusterer.generate_summary(["a", "b", "c"])

        assert "3 wallets" in summary
        assert "2 cluster" in summary
        assert "SOL" in summary


class TestCTOScorer:
    """Tests for CTOScorer."""

    def setup_method(self):
        self.mock_clusterer = MagicMock(spec=WalletClusterer)
        self.mock_clusterer.get_cluster_for_wallets.return_value = []
        self.scorer = CTOScorer(self.mock_clusterer)

    def test_score_high_concentration(self):
        """Test scoring high concentration."""
        stats = TokenStats(
            mint="test",
            window_seconds=300,
            buy_count=50,
            unique_buyers=5,
            volume_sol=10.0,
            top_3_volume_share=0.85,  # Very high concentration
            new_wallet_pct=0.3,
            buy_sell_ratio=5.0,
        )
        top_buyers = [{"wallet": f"wallet_{i}"} for i in range(5)]

        score = self.scorer.score_token(stats, top_buyers)

        assert score.concentration_score == 1.0
        assert "concentration" in score.evidence[0].lower()

    def test_score_high_new_wallet(self):
        """Test scoring high new wallet percentage."""
        stats = TokenStats(
            mint="test",
            window_seconds=300,
            buy_count=50,
            unique_buyers=10,
            volume_sol=10.0,
            top_3_volume_share=0.3,
            new_wallet_pct=0.75,  # Very high new wallet %
            buy_sell_ratio=3.0,
        )
        top_buyers = [{"wallet": f"wallet_{i}"} for i in range(5)]

        score = self.scorer.score_token(stats, top_buyers)

        assert score.new_wallet_score == 1.0

    def test_score_extreme_ratio(self):
        """Test scoring extreme buy/sell ratio."""
        stats = TokenStats(
            mint="test",
            window_seconds=300,
            buy_count=100,
            sell_count=0,
            unique_buyers=20,
            volume_sol=10.0,
            top_3_volume_share=0.3,
            new_wallet_pct=0.2,
            buy_sell_ratio=float('inf'),  # All buys
        )
        top_buyers = [{"wallet": f"wallet_{i}"} for i in range(5)]

        score = self.scorer.score_token(stats, top_buyers)

        assert score.ratio_score == 1.0
        assert any("buy" in e.lower() for e in score.evidence)

    def test_get_risk_level(self):
        """Test risk level calculation."""
        high_score = CTOScore(total_score=0.75, confidence=0.8)
        medium_score = CTOScore(total_score=0.45, confidence=0.8)
        low_score = CTOScore(total_score=0.25, confidence=0.8)
        minimal_score = CTOScore(total_score=0.1, confidence=0.8)

        assert self.scorer.get_risk_level(high_score) == "HIGH"
        assert self.scorer.get_risk_level(medium_score) == "MEDIUM"
        assert self.scorer.get_risk_level(low_score) == "LOW"
        assert self.scorer.get_risk_level(minimal_score) == "MINIMAL"
