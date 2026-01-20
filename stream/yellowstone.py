"""Yellowstone gRPC client for Solana transaction streaming."""

import asyncio
import logging
import time
from typing import AsyncIterator, Callable, Dict, List, Optional, Set

import grpc
import yaml
from grpc import aio as grpc_aio

from config.settings import settings

logger = logging.getLogger(__name__)

# Import generated protobuf modules
# Note: These need to be generated from the Yellowstone proto files
# pip install grpcio-tools
# python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. yellowstone.proto
try:
    from . import geyser_pb2
    from . import geyser_pb2_grpc
except ImportError:
    logger.warning("Yellowstone protobuf modules not found. Run proto generation first.")
    geyser_pb2 = None
    geyser_pb2_grpc = None


class YellowstoneClient:
    """
    Yellowstone gRPC client for streaming Solana transactions.

    Connects to Chainstack Yellowstone gRPC endpoint and streams
    transactions filtered by program IDs.
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        token: Optional[str] = None,
        programs_file: str = "config/programs.yaml",
    ):
        self.endpoint = endpoint or settings.yellowstone_endpoint
        self.token = token or settings.yellowstone_token
        self.programs_file = programs_file

        self._channel: Optional[grpc_aio.Channel] = None
        self._stub = None
        self._program_ids: Set[str] = set()
        self._program_names: Dict[str, str] = {}
        self._running = False
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0

        # Stats
        self._tx_count = 0
        self._last_slot = 0
        self._last_block_time = 0
        self._start_time = 0

    async def load_programs(self):
        """Load program IDs from config file."""
        try:
            with open(self.programs_file, "r") as f:
                config = yaml.safe_load(f)

            self._program_ids = set()
            self._program_names = {}

            for prog in config.get("programs", []):
                prog_id = prog["id"]
                name = prog.get("name", prog_id[:8])
                self._program_ids.add(prog_id)
                self._program_names[prog_id] = name

            logger.info(f"Loaded {len(self._program_ids)} program IDs")
        except Exception as e:
            logger.error(f"Failed to load programs config: {e}")
            raise

    @property
    def program_ids(self) -> Set[str]:
        """Get current program IDs."""
        return self._program_ids

    @property
    def known_programs(self) -> Set[str]:
        """Get known program IDs (alias for program_ids)."""
        return self._program_ids

    def get_program_name(self, program_id: str) -> str:
        """Get human-readable name for a program ID."""
        return self._program_names.get(program_id, program_id[:8])

    async def connect(self):
        """Establish gRPC connection."""
        if geyser_pb2 is None:
            raise RuntimeError("Yellowstone protobuf modules not available")

        # Create channel with auth metadata
        credentials = grpc.ssl_channel_credentials()
        call_credentials = grpc.metadata_call_credentials(
            lambda context, callback: callback(
                [("x-token", self.token)],
                None
            )
        )
        composite_credentials = grpc.composite_channel_credentials(
            credentials, call_credentials
        )

        self._channel = grpc_aio.secure_channel(
            self.endpoint,
            composite_credentials,
            options=[
                ("grpc.max_receive_message_length", 64 * 1024 * 1024),
                ("grpc.keepalive_time_ms", 10000),
                ("grpc.keepalive_timeout_ms", 5000),
                ("grpc.keepalive_permit_without_calls", True),
            ]
        )

        self._stub = geyser_pb2_grpc.GeyserStub(self._channel)
        logger.info(f"Connected to Yellowstone at {self.endpoint}")

    async def disconnect(self):
        """Close gRPC connection."""
        self._running = False
        if self._channel:
            await self._channel.close()
            self._channel = None
            self._stub = None
        logger.info("Disconnected from Yellowstone")

    def _build_subscribe_request(self):
        """Build subscription request with program filters."""
        if geyser_pb2 is None:
            raise RuntimeError("Yellowstone protobuf modules not available")

        # Build transaction filter for our programs
        tx_filter = geyser_pb2.SubscribeRequestFilterTransactions(
            vote=False,
            failed=False,
            account_include=list(self._program_ids),
        )

        request = geyser_pb2.SubscribeRequest(
            transactions={"programs": tx_filter},
        )

        return request

    async def _request_iterator(self):
        """
        Async generator that yields subscribe requests.
        For bidirectional streaming, we send one initial request then keep connection open.
        """
        yield self._build_subscribe_request()
        # Keep the stream open by not returning - we just don't send more requests
        # The server will keep sending us updates
        while self._running:
            await asyncio.sleep(30)  # Send periodic ping to keep alive
            yield geyser_pb2.SubscribeRequest(
                ping=geyser_pb2.SubscribeRequestPing(id=int(time.time()))
            )

    async def stream_transactions(
        self,
        on_transaction: Callable,
        on_error: Optional[Callable] = None,
    ):
        """
        Stream transactions and call handler for each.

        Args:
            on_transaction: Async callback receiving raw transaction data
            on_error: Optional callback for errors
        """
        self._running = True
        self._start_time = time.time()

        while self._running:
            try:
                if not self._stub:
                    await self.connect()

                # Bidirectional streaming: pass request iterator, get response iterator
                response_stream = self._stub.Subscribe(self._request_iterator())

                async for response in response_stream:
                    if not self._running:
                        break

                    # Handle different update types
                    if response.HasField("transaction"):
                        tx = response.transaction
                        self._tx_count += 1
                        self._last_slot = tx.slot

                        try:
                            await on_transaction(tx)
                        except Exception as e:
                            logger.error(f"Error processing transaction: {e}")
                            if on_error:
                                await on_error(e)

                    elif response.HasField("pong"):
                        logger.debug(f"Received pong: {response.pong.id}")

                    # Reset reconnect delay on successful message
                    self._reconnect_delay = 1.0

            except grpc.RpcError as e:
                logger.error(f"gRPC error: {e.code()} - {e.details()}")
                if on_error:
                    await on_error(e)

                if self._running:
                    logger.info(f"Reconnecting in {self._reconnect_delay}s...")
                    await asyncio.sleep(self._reconnect_delay)
                    self._reconnect_delay = min(
                        self._reconnect_delay * 2,
                        self._max_reconnect_delay
                    )
                    # Reset connection
                    await self.disconnect()

            except Exception as e:
                logger.error(f"Unexpected error in stream: {e}")
                if on_error:
                    await on_error(e)

                if self._running:
                    await asyncio.sleep(self._reconnect_delay)
                    self._reconnect_delay = min(
                        self._reconnect_delay * 2,
                        self._max_reconnect_delay
                    )

    def stop(self):
        """Signal to stop streaming."""
        self._running = False

    def get_stats(self) -> dict:
        """Get streaming statistics."""
        uptime = time.time() - self._start_time if self._start_time > 0 else 0
        tx_per_sec = self._tx_count / uptime if uptime > 0 else 0

        return {
            "tx_count": self._tx_count,
            "last_slot": self._last_slot,
            "last_block_time": self._last_block_time,
            "uptime_seconds": uptime,
            "tx_per_second": tx_per_sec,
            "running": self._running,
            "program_count": len(self._program_ids),
        }


class MockYellowstoneClient(YellowstoneClient):
    """
    Mock Yellowstone client for testing without a real connection.

    Generates synthetic transaction data for development and testing.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._mock_tx_generator = None

    async def connect(self):
        """Mock connection."""
        logger.info("Mock Yellowstone client connected")

    async def disconnect(self):
        """Mock disconnect."""
        self._running = False
        logger.info("Mock Yellowstone client disconnected")

    async def stream_transactions(
        self,
        on_transaction: Callable,
        on_error: Optional[Callable] = None,
    ):
        """Generate mock transactions for testing."""
        self._running = True
        self._start_time = time.time()

        import random

        # Mock mints for testing
        mock_mints = [
            f"Mock{i}mintAddress" + "x" * 32
            for i in range(10)
        ]

        while self._running:
            try:
                # Generate a mock transaction
                mock_tx = self._generate_mock_tx(mock_mints)
                self._tx_count += 1
                self._last_slot += 1
                self._last_block_time = int(time.time())

                await on_transaction(mock_tx)

                # Random delay to simulate realistic traffic
                await asyncio.sleep(random.uniform(0.01, 0.1))

            except Exception as e:
                logger.error(f"Error in mock stream: {e}")
                if on_error:
                    await on_error(e)

    def _generate_mock_tx(self, mints: List[str]) -> dict:
        """Generate a mock transaction for testing."""
        import random
        import base58

        mint = random.choice(mints)
        user_wallet = base58.b58encode(bytes(random.getrandbits(8) for _ in range(32))).decode()

        # Simulate buy or sell
        is_buy = random.random() > 0.3  # 70% buys
        quote_amount = int(random.uniform(0.1, 10) * 1e9)  # 0.1-10 SOL in lamports
        base_amount = int(random.uniform(1000, 1000000) * 1e6)  # Token amount

        return {
            "signature": base58.b58encode(bytes(random.getrandbits(8) for _ in range(64))).decode(),
            "slot": self._last_slot + 1,
            "block_time": int(time.time()),
            "fee_payer": user_wallet,
            "programs_invoked": [random.choice(list(self._program_ids))] if self._program_ids else [],
            "pre_token_balances": [
                {"owner": user_wallet, "mint": mint, "amount": 0 if is_buy else base_amount},
            ],
            "post_token_balances": [
                {"owner": user_wallet, "mint": mint, "amount": base_amount if is_buy else 0},
            ],
            "pre_balances": {user_wallet: quote_amount + 100000 if is_buy else 100000},
            "post_balances": {user_wallet: 100000 if is_buy else quote_amount + 100000},
            "fee": 5000,
        }
