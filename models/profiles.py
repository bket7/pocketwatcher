"""Profile models for tokens and wallets."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Set
import json


class TokenState(str, Enum):
    """Token monitoring state."""
    COLD = "cold"    # Aggregates only
    WARM = "warm"    # Per-swap events 30-60 min
    HOT = "hot"      # Full enrichment + clustering


@dataclass
class TokenProfile:
    """Token profile with monitoring state and metadata."""
    mint: str
    state: TokenState = TokenState.COLD

    # Timestamps
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    became_hot_at: Optional[datetime] = None

    # Aggregated stats
    total_buys: int = 0
    total_sells: int = 0
    total_volume_sol: float = 0.0
    unique_buyers: int = 0
    unique_sellers: int = 0

    # Detection metadata
    trigger_reason: Optional[str] = None

    # Token metadata (fetched on HOT)
    name: Optional[str] = None
    symbol: Optional[str] = None
    decimals: int = 9

    def to_dict(self) -> dict:
        """Convert to dictionary for database storage."""
        return {
            "mint": self.mint,
            "state": self.state.value,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "became_hot_at": self.became_hot_at.isoformat() if self.became_hot_at else None,
            "total_buys": self.total_buys,
            "total_sells": self.total_sells,
            "total_volume_sol": self.total_volume_sol,
            "unique_buyers": self.unique_buyers,
            "unique_sellers": self.unique_sellers,
            "trigger_reason": self.trigger_reason,
            "name": self.name,
            "symbol": self.symbol,
            "decimals": self.decimals,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TokenProfile":
        """Create from dictionary."""
        return cls(
            mint=d["mint"],
            state=TokenState(d["state"]),
            first_seen=datetime.fromisoformat(d["first_seen"]) if d.get("first_seen") else None,
            last_seen=datetime.fromisoformat(d["last_seen"]) if d.get("last_seen") else None,
            became_hot_at=datetime.fromisoformat(d["became_hot_at"]) if d.get("became_hot_at") else None,
            total_buys=d.get("total_buys", 0),
            total_sells=d.get("total_sells", 0),
            total_volume_sol=d.get("total_volume_sol", 0.0),
            unique_buyers=d.get("unique_buyers", 0),
            unique_sellers=d.get("unique_sellers", 0),
            trigger_reason=d.get("trigger_reason"),
            name=d.get("name"),
            symbol=d.get("symbol"),
            decimals=d.get("decimals", 9),
        )


@dataclass
class WalletProfile:
    """Wallet profile with activity and cluster information."""
    address: str

    # Timestamps
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None

    # Activity stats
    total_buys: int = 0
    total_sells: int = 0
    total_volume_sol: float = 0.0
    tokens_traded: Set[str] = field(default_factory=set)

    # Cluster information (union-find)
    cluster_id: Optional[str] = None
    cluster_size: int = 1

    # Funding analysis
    funded_by: Optional[str] = None
    funding_amount_sol: Optional[float] = None
    funding_hop: int = 0  # 0 = direct, 1 = one hop, etc.

    # Risk indicators
    is_new_wallet: bool = False  # First seen in our data
    cto_score: float = 0.0  # CTO likelihood score

    def to_dict(self) -> dict:
        """Convert to dictionary for database storage."""
        return {
            "address": self.address,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "total_buys": self.total_buys,
            "total_sells": self.total_sells,
            "total_volume_sol": self.total_volume_sol,
            "tokens_traded": list(self.tokens_traded),
            "cluster_id": self.cluster_id,
            "cluster_size": self.cluster_size,
            "funded_by": self.funded_by,
            "funding_amount_sol": self.funding_amount_sol,
            "funding_hop": self.funding_hop,
            "is_new_wallet": self.is_new_wallet,
            "cto_score": self.cto_score,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WalletProfile":
        """Create from dictionary."""
        return cls(
            address=d["address"],
            first_seen=datetime.fromisoformat(d["first_seen"]) if d.get("first_seen") else None,
            last_seen=datetime.fromisoformat(d["last_seen"]) if d.get("last_seen") else None,
            total_buys=d.get("total_buys", 0),
            total_sells=d.get("total_sells", 0),
            total_volume_sol=d.get("total_volume_sol", 0.0),
            tokens_traded=set(d.get("tokens_traded", [])),
            cluster_id=d.get("cluster_id"),
            cluster_size=d.get("cluster_size", 1),
            funded_by=d.get("funded_by"),
            funding_amount_sol=d.get("funding_amount_sol"),
            funding_hop=d.get("funding_hop", 0),
            is_new_wallet=d.get("is_new_wallet", False),
            cto_score=d.get("cto_score", 0.0),
        )


@dataclass
class Alert:
    """Alert generated when detection triggers fire."""
    id: Optional[int] = None

    # Token info
    mint: str = ""
    token_name: Optional[str] = None
    token_symbol: Optional[str] = None

    # Trigger info
    trigger_name: str = ""
    trigger_reason: str = ""

    # Stats at time of alert
    buy_count_5m: int = 0
    unique_buyers_5m: int = 0
    volume_sol_5m: float = 0.0
    buy_sell_ratio_5m: float = 0.0

    # Enrichment data (if available)
    top_buyers: List[Dict] = field(default_factory=list)
    cluster_summary: Optional[str] = None
    enrichment_degraded: bool = False

    # Price/Market cap at alert time
    price_sol: Optional[float] = None      # Price per token in SOL
    mcap_sol: Optional[float] = None       # Market cap in SOL
    token_supply: Optional[int] = None     # Total supply (raw, not decimal-adjusted)

    # Timestamps
    created_at: Optional[datetime] = None

    # Delivery status
    discord_sent: bool = False
    telegram_sent: bool = False

    def to_dict(self) -> dict:
        """Convert to dictionary for database storage."""
        return {
            "id": self.id,
            "mint": self.mint,
            "token_name": self.token_name,
            "token_symbol": self.token_symbol,
            "trigger_name": self.trigger_name,
            "trigger_reason": self.trigger_reason,
            "buy_count_5m": self.buy_count_5m,
            "unique_buyers_5m": self.unique_buyers_5m,
            "volume_sol_5m": self.volume_sol_5m,
            "buy_sell_ratio_5m": self.buy_sell_ratio_5m,
            "top_buyers": self.top_buyers,
            "cluster_summary": self.cluster_summary,
            "enrichment_degraded": self.enrichment_degraded,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "discord_sent": self.discord_sent,
            "telegram_sent": self.telegram_sent,
            "price_sol": self.price_sol,
            "mcap_sol": self.mcap_sol,
            "token_supply": self.token_supply,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Alert":
        """Create from dictionary."""
        return cls(
            id=d.get("id"),
            mint=d["mint"],
            token_name=d.get("token_name"),
            token_symbol=d.get("token_symbol"),
            trigger_name=d["trigger_name"],
            trigger_reason=d["trigger_reason"],
            buy_count_5m=d.get("buy_count_5m", 0),
            unique_buyers_5m=d.get("unique_buyers_5m", 0),
            volume_sol_5m=d.get("volume_sol_5m", 0.0),
            buy_sell_ratio_5m=d.get("buy_sell_ratio_5m", 0.0),
            top_buyers=d.get("top_buyers", []),
            cluster_summary=d.get("cluster_summary"),
            enrichment_degraded=d.get("enrichment_degraded", False),
            created_at=datetime.fromisoformat(d["created_at"]) if d.get("created_at") else None,
            discord_sent=d.get("discord_sent", False),
            telegram_sent=d.get("telegram_sent", False),
            price_sol=d.get("price_sol"),
            mcap_sol=d.get("mcap_sol"),
            token_supply=d.get("token_supply"),
        )
