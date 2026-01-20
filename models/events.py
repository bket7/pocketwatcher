"""Event models for transaction processing."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple
import msgpack
import time


class SwapSide(str, Enum):
    """Swap direction."""
    BUY = "buy"
    SELL = "sell"


@dataclass
class MintTouchedEvent:
    """
    Emitted for ALL ingested transactions - never miss a token.

    This is the lightweight event that ensures we track every token
    touched by any transaction, regardless of whether we can parse
    the full swap details.
    """
    signature: str
    slot: int
    block_time: int
    fee_payer: str
    mints_touched: Set[str]
    programs_invoked: Set[str]
    compute_units: Optional[int] = None

    def to_msgpack(self) -> bytes:
        """Serialize to msgpack for storage."""
        return msgpack.packb({
            "sig": self.signature,
            "slot": self.slot,
            "bt": self.block_time,
            "fp": self.fee_payer,
            "mints": list(self.mints_touched),
            "progs": list(self.programs_invoked),
            "cu": self.compute_units,
        })

    @classmethod
    def from_msgpack(cls, data: bytes) -> "MintTouchedEvent":
        """Deserialize from msgpack."""
        d = msgpack.unpackb(data)
        return cls(
            signature=d["sig"],
            slot=d["slot"],
            block_time=d["bt"],
            fee_payer=d["fp"],
            mints_touched=set(d["mints"]),
            programs_invoked=set(d["progs"]),
            compute_units=d.get("cu"),
        )


@dataclass
class TxDeltaRecord:
    """
    Rich delta record stored for ALL transactions (60 min retention).

    Contains enough data to reconstruct swaps when a token becomes HOT,
    without requiring paid API calls for historical data.
    """
    signature: str
    slot: int
    block_time: int
    fee_payer: str
    programs_invoked: Set[str]

    # Token deltas: (owner, mint, delta)
    token_deltas: List[Tuple[str, str, int]]

    # SOL deltas per account (already fee/rent adjusted)
    sol_deltas: Dict[str, int]

    # Derived
    mints_touched: Set[str]

    # Optional metadata for debugging
    tx_fee: int = 0
    accounts_created: int = 0

    def to_msgpack(self) -> bytes:
        """Serialize to msgpack for storage."""
        return msgpack.packb({
            "sig": self.signature,
            "slot": self.slot,
            "bt": self.block_time,
            "fp": self.fee_payer,
            "progs": list(self.programs_invoked),
            "td": self.token_deltas,
            "sd": self.sol_deltas,
            "mints": list(self.mints_touched),
            "fee": self.tx_fee,
            "ac": self.accounts_created,
        })

    @classmethod
    def from_msgpack(cls, data: bytes) -> "TxDeltaRecord":
        """Deserialize from msgpack."""
        d = msgpack.unpackb(data)
        return cls(
            signature=d["sig"],
            slot=d["slot"],
            block_time=d["bt"],
            fee_payer=d["fp"],
            programs_invoked=set(d["progs"]),
            token_deltas=[(t[0], t[1], t[2]) for t in d["td"]],
            sol_deltas=d["sd"],
            mints_touched=set(d["mints"]),
            tx_fee=d.get("fee", 0),
            accounts_created=d.get("ac", 0),
        )


@dataclass
class SwapEventFull:
    """
    Full swap event stored only for HOT/WARM tokens.

    Represents a parsed swap with high confidence (>= 0.7).
    """
    signature: str
    slot: int
    block_time: int

    venue: str  # pump | jupiter | raydium | orca | meteora
    user_wallet: str

    side: SwapSide
    base_mint: str
    base_amount: int
    quote_mint: str
    quote_amount: int

    confidence: float
    route_depth: int = 1

    def to_dict(self) -> dict:
        """Convert to dictionary for database storage."""
        return {
            "signature": self.signature,
            "slot": self.slot,
            "block_time": self.block_time,
            "venue": self.venue,
            "user_wallet": self.user_wallet,
            "side": self.side.value if isinstance(self.side, SwapSide) else self.side,
            "base_mint": self.base_mint,
            "base_amount": self.base_amount,
            "quote_mint": self.quote_mint,
            "quote_amount": self.quote_amount,
            "confidence": self.confidence,
            "route_depth": self.route_depth,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SwapEventFull":
        """Create from dictionary."""
        return cls(
            signature=d["signature"],
            slot=d["slot"],
            block_time=d["block_time"],
            venue=d["venue"],
            user_wallet=d["user_wallet"],
            side=SwapSide(d["side"]) if isinstance(d["side"], str) else d["side"],
            base_mint=d["base_mint"],
            base_amount=d["base_amount"],
            quote_mint=d["quote_mint"],
            quote_amount=d["quote_amount"],
            confidence=d["confidence"],
            route_depth=d.get("route_depth", 1),
        )

    def to_msgpack(self) -> bytes:
        """Serialize to msgpack."""
        return msgpack.packb(self.to_dict())

    @classmethod
    def from_msgpack(cls, data: bytes) -> "SwapEventFull":
        """Deserialize from msgpack."""
        return cls.from_dict(msgpack.unpackb(data))


@dataclass
class SwapCandidate:
    """Intermediate swap candidate before full event creation."""
    user_wallet: str
    side: SwapSide
    base_mint: str
    base_amount: int
    quote_mint: str
    quote_amount: int
    confidence: float
