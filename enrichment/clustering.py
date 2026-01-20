"""Wallet clustering using union-find algorithm."""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from storage.postgres_client import PostgresClient
from models.profiles import WalletProfile

logger = logging.getLogger(__name__)


@dataclass
class Cluster:
    """A cluster of related wallets."""
    id: str  # Root wallet address
    members: Set[str] = field(default_factory=set)
    total_volume_sol: float = 0.0
    total_buys: int = 0

    @property
    def size(self) -> int:
        return len(self.members)


class UnionFind:
    """
    Union-Find (Disjoint Set Union) data structure.

    Used to efficiently merge wallet clusters when
    funding relationships are discovered.
    """

    def __init__(self):
        self.parent: Dict[str, str] = {}
        self.rank: Dict[str, int] = {}

    def find(self, x: str) -> str:
        """Find root of set containing x with path compression."""
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
            return x

        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])

        return self.parent[x]

    def union(self, x: str, y: str) -> str:
        """
        Union sets containing x and y.

        Returns the new root.
        """
        root_x = self.find(x)
        root_y = self.find(y)

        if root_x == root_y:
            return root_x

        # Union by rank
        if self.rank[root_x] < self.rank[root_y]:
            self.parent[root_x] = root_y
            return root_y
        elif self.rank[root_x] > self.rank[root_y]:
            self.parent[root_y] = root_x
            return root_x
        else:
            self.parent[root_y] = root_x
            self.rank[root_x] += 1
            return root_x

    def connected(self, x: str, y: str) -> bool:
        """Check if x and y are in the same set."""
        return self.find(x) == self.find(y)

    def get_all_clusters(self) -> Dict[str, Set[str]]:
        """Get all clusters as root -> members mapping."""
        clusters: Dict[str, Set[str]] = {}

        for node in self.parent:
            root = self.find(node)
            if root not in clusters:
                clusters[root] = set()
            clusters[root].add(node)

        return clusters


class WalletClusterer:
    """
    Clusters wallets based on funding relationships.

    Uses union-find to efficiently merge clusters when
    wallets are discovered to be related (funded by same source).
    """

    def __init__(self, postgres_client: PostgresClient):
        self.postgres = postgres_client
        self._union_find = UnionFind()
        self._wallet_volumes: Dict[str, float] = {}
        self._wallet_buys: Dict[str, int] = {}

    def add_wallet(
        self,
        address: str,
        volume_sol: float = 0.0,
        buy_count: int = 0
    ):
        """Add a wallet to tracking."""
        self._union_find.find(address)  # Ensure in union-find
        self._wallet_volumes[address] = self._wallet_volumes.get(address, 0) + volume_sol
        self._wallet_buys[address] = self._wallet_buys.get(address, 0) + buy_count

    def link_wallets(self, wallet1: str, wallet2: str):
        """
        Link two wallets as related (same cluster).

        Called when funding relationship is discovered.
        """
        self._union_find.union(wallet1, wallet2)
        logger.debug(f"Linked wallets {wallet1[:8]} <-> {wallet2[:8]}")

    def link_funding(self, wallet: str, funder: str):
        """Link wallet to its funder."""
        self.add_wallet(wallet)
        self.add_wallet(funder)
        self.link_wallets(wallet, funder)

    def get_cluster(self, wallet: str) -> Cluster:
        """Get the cluster containing a wallet."""
        root = self._union_find.find(wallet)
        clusters = self._union_find.get_all_clusters()
        members = clusters.get(root, {wallet})

        # Aggregate stats
        total_volume = sum(self._wallet_volumes.get(m, 0) for m in members)
        total_buys = sum(self._wallet_buys.get(m, 0) for m in members)

        return Cluster(
            id=root,
            members=members,
            total_volume_sol=total_volume,
            total_buys=total_buys,
        )

    def get_cluster_for_wallets(self, wallets: List[str]) -> List[Cluster]:
        """Get clusters for a list of wallets, deduped."""
        seen_roots = set()
        clusters = []

        for wallet in wallets:
            root = self._union_find.find(wallet)
            if root not in seen_roots:
                seen_roots.add(root)
                clusters.append(self.get_cluster(wallet))

        return clusters

    def get_all_clusters(self) -> List[Cluster]:
        """Get all clusters."""
        raw_clusters = self._union_find.get_all_clusters()
        clusters = []

        for root, members in raw_clusters.items():
            total_volume = sum(self._wallet_volumes.get(m, 0) for m in members)
            total_buys = sum(self._wallet_buys.get(m, 0) for m in members)

            clusters.append(Cluster(
                id=root,
                members=members,
                total_volume_sol=total_volume,
                total_buys=total_buys,
            ))

        return clusters

    def get_large_clusters(self, min_size: int = 2) -> List[Cluster]:
        """Get clusters with at least min_size members."""
        return [c for c in self.get_all_clusters() if c.size >= min_size]

    async def persist_cluster(self, cluster: Cluster):
        """Persist cluster information to database."""
        for member in cluster.members:
            await self.postgres.update_wallet_cluster(
                address=member,
                cluster_id=cluster.id,
                cluster_size=cluster.size,
            )

    async def persist_all_clusters(self):
        """Persist all clusters to database."""
        for cluster in self.get_all_clusters():
            await self.persist_cluster(cluster)

    def generate_summary(self, wallets: List[str]) -> str:
        """
        Generate human-readable cluster summary for alerts.

        Example output:
        "3 wallets in 2 clusters: Cluster A (2 wallets, 5.5 SOL), Cluster B (1 wallet, 2.1 SOL)"
        """
        clusters = self.get_cluster_for_wallets(wallets)

        if not clusters:
            return "No cluster data available"

        # Sort by volume
        clusters.sort(key=lambda c: c.total_volume_sol, reverse=True)

        total_wallets = sum(c.size for c in clusters)
        cluster_count = len(clusters)

        parts = []
        for i, cluster in enumerate(clusters[:5]):  # Top 5 clusters
            parts.append(
                f"Cluster {chr(65+i)} ({cluster.size} wallet{'s' if cluster.size > 1 else ''}, "
                f"{cluster.total_volume_sol:.2f} SOL)"
            )

        summary = f"{total_wallets} wallets in {cluster_count} cluster{'s' if cluster_count > 1 else ''}"

        if parts:
            summary += ": " + ", ".join(parts)

        if cluster_count > 5:
            summary += f" (+{cluster_count - 5} more clusters)"

        return summary

    def get_stats(self) -> dict:
        """Get clustering statistics."""
        clusters = self.get_all_clusters()
        large_clusters = [c for c in clusters if c.size >= 2]

        return {
            "total_wallets": len(self._union_find.parent),
            "total_clusters": len(clusters),
            "large_clusters": len(large_clusters),
            "avg_cluster_size": (
                sum(c.size for c in clusters) / len(clusters)
                if clusters
                else 0
            ),
            "max_cluster_size": max((c.size for c in clusters), default=0),
        }
