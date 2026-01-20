"""
Yellowstone gRPC Protobuf Stubs (Placeholder)

To generate real stubs, run:

1. Download the Yellowstone proto files:
   - https://github.com/rpcpool/yellowstone-grpc/tree/master/yellowstone-grpc-proto/proto

2. Generate Python stubs:
   python -m grpc_tools.protoc \\
       -I./proto \\
       --python_out=./stream \\
       --grpc_python_out=./stream \\
       proto/geyser.proto

For now, this placeholder provides the minimum interface needed.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class SubscribeRequestFilterTransactions:
    """Transaction filter for subscription."""
    vote: bool = False
    failed: bool = False
    account_include: List[str] = field(default_factory=list)
    account_exclude: List[str] = field(default_factory=list)
    account_required: List[str] = field(default_factory=list)


@dataclass
class SubscribeRequest:
    """Subscription request."""
    transactions: Dict[str, SubscribeRequestFilterTransactions] = field(default_factory=dict)
    accounts: Dict[str, Any] = field(default_factory=dict)
    slots: Dict[str, Any] = field(default_factory=dict)
    blocks: Dict[str, Any] = field(default_factory=dict)
    blocks_meta: Dict[str, Any] = field(default_factory=dict)
    entry: Dict[str, Any] = field(default_factory=dict)
    commitment: Optional[int] = None
    accounts_data_slice: List[Any] = field(default_factory=list)


@dataclass
class UiTokenAmount:
    """Token amount with UI formatting."""
    amount: str = "0"
    decimals: int = 0
    ui_amount: Optional[float] = None
    ui_amount_string: str = ""


@dataclass
class TokenBalance:
    """Token balance entry."""
    account_index: int = 0
    mint: str = ""
    owner: str = ""
    program_id: str = ""
    ui_token_amount: UiTokenAmount = field(default_factory=UiTokenAmount)


@dataclass
class InnerInstruction:
    """Inner instruction."""
    program_id: str = ""
    accounts: List[int] = field(default_factory=list)
    data: bytes = b""


@dataclass
class InnerInstructions:
    """Inner instructions for an instruction index."""
    index: int = 0
    instructions: List[InnerInstruction] = field(default_factory=list)


@dataclass
class TransactionStatusMeta:
    """Transaction metadata."""
    err: Optional[Any] = None
    fee: int = 0
    pre_balances: List[int] = field(default_factory=list)
    post_balances: List[int] = field(default_factory=list)
    pre_token_balances: List[TokenBalance] = field(default_factory=list)
    post_token_balances: List[TokenBalance] = field(default_factory=list)
    inner_instructions: List[InnerInstructions] = field(default_factory=list)
    log_messages: List[str] = field(default_factory=list)
    loaded_writable_addresses: List[str] = field(default_factory=list)
    loaded_readonly_addresses: List[str] = field(default_factory=list)
    compute_units_consumed: Optional[int] = None


@dataclass
class CompiledInstruction:
    """Compiled instruction."""
    program_id_index: int = 0
    accounts: List[int] = field(default_factory=list)
    data: bytes = b""


@dataclass
class MessageHeader:
    """Message header."""
    num_required_signatures: int = 0
    num_readonly_signed_accounts: int = 0
    num_readonly_unsigned_accounts: int = 0


@dataclass
class Message:
    """Transaction message."""
    header: MessageHeader = field(default_factory=MessageHeader)
    account_keys: List[str] = field(default_factory=list)
    recent_blockhash: str = ""
    instructions: List[CompiledInstruction] = field(default_factory=list)
    versioned: bool = False
    address_table_lookups: List[Any] = field(default_factory=list)


@dataclass
class Transaction:
    """Transaction."""
    signatures: List[str] = field(default_factory=list)
    message: Message = field(default_factory=Message)


@dataclass
class SubscribeUpdateTransaction:
    """Transaction update."""
    transaction: Transaction = field(default_factory=Transaction)
    meta: TransactionStatusMeta = field(default_factory=TransactionStatusMeta)
    slot: int = 0
    signature: str = ""
    is_vote: bool = False
    block_time: Optional[int] = None


@dataclass
class SubscribeUpdate:
    """Subscribe update union type."""
    transaction: Optional[SubscribeUpdateTransaction] = None
    filters: List[str] = field(default_factory=list)

    def HasField(self, name: str) -> bool:
        """Check if field is set."""
        if name == "transaction":
            return self.transaction is not None
        return False
