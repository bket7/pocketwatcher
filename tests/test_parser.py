"""Tests for parser module."""

import pytest
from parser.deltas import DeltaBuilder, WSOL_MINT, QUOTE_MINTS
from parser.inference import SwapInference
from models.events import SwapSide


class TestDeltaBuilder:
    """Tests for DeltaBuilder."""

    def setup_method(self):
        self.builder = DeltaBuilder()

    def test_build_deltas_simple_buy(self):
        """Test building deltas for a simple buy transaction."""
        tx_data = {
            "account_keys": ["user_wallet", "pool", "token_account"],
            "fee_payer": "user_wallet",
            "fee": 5000,
            "pre_token_balances": [
                {"owner": "user_wallet", "mint": "token_mint", "amount": "0"}
            ],
            "post_token_balances": [
                {"owner": "user_wallet", "mint": "token_mint", "amount": "1000000"}
            ],
            "pre_balances": {"user_wallet": 10000000000, "pool": 5000000000},
            "post_balances": {"user_wallet": 9000000000, "pool": 6000000000},
        }

        token_deltas, sol_deltas = self.builder.build_deltas(tx_data)

        # User received 1M tokens
        assert token_deltas.get(("user_wallet", "token_mint")) == 1000000

        # User spent SOL (after fee correction)
        assert sol_deltas.get("user_wallet") < 0

    def test_build_deltas_with_fee_correction(self):
        """Test that transaction fee is correctly added back."""
        tx_data = {
            "account_keys": ["fee_payer"],
            "fee_payer": "fee_payer",
            "fee": 5000,
            "pre_token_balances": [],
            "post_token_balances": [],
            "pre_balances": {"fee_payer": 1000000000},
            "post_balances": {"fee_payer": 999995000},  # 1B - 5000 fee
        }

        token_deltas, sol_deltas = self.builder.build_deltas(tx_data)

        # Delta should be 0 after fee correction (only fee was paid)
        assert sol_deltas.get("fee_payer", 0) == 0

    def test_normalize_wsol_to_sol(self):
        """Test WSOL normalization."""
        token_deltas = {
            ("user", WSOL_MINT): -500000000,  # Spent 0.5 WSOL
            ("user", "other_token"): 1000000,
        }
        sol_deltas = {
            "user": 0,
        }

        merged = self.builder.normalize_wsol_to_sol(token_deltas, sol_deltas)

        # Should have merged WSOL into SOL delta
        assert merged["user"] == -500000000

    def test_extract_mints_touched(self):
        """Test mint extraction excludes WSOL."""
        token_deltas = {
            ("user", WSOL_MINT): -100,
            ("user", "token_a"): 100,
            ("user", "token_b"): -50,
        }

        mints = self.builder.extract_mints_touched(token_deltas)

        assert WSOL_MINT not in mints
        assert "token_a" in mints
        assert "token_b" in mints


class TestSwapInference:
    """Tests for SwapInference."""

    def setup_method(self):
        self.inference = SwapInference()

    def test_infer_buy(self):
        """Test detecting a buy swap."""
        token_deltas = {
            ("user", "meme_token"): 1000000,  # Received meme token
        }
        sol_deltas = {
            "user": -500000000,  # Spent 0.5 SOL
        }
        candidates = {"user"}

        swap = self.inference.infer_swap(token_deltas, sol_deltas, candidates)

        assert swap is not None
        assert swap.side == SwapSide.BUY
        assert swap.base_mint == "meme_token"
        assert swap.base_amount == 1000000
        assert swap.quote_mint == WSOL_MINT
        assert swap.quote_amount == 500000000
        assert swap.confidence > 0.7

    def test_infer_sell(self):
        """Test detecting a sell swap."""
        token_deltas = {
            ("user", "meme_token"): -1000000,  # Sold meme token
        }
        sol_deltas = {
            "user": 500000000,  # Received 0.5 SOL
        }
        candidates = {"user"}

        swap = self.inference.infer_swap(token_deltas, sol_deltas, candidates)

        assert swap is not None
        assert swap.side == SwapSide.SELL
        assert swap.base_mint == "meme_token"
        assert swap.base_amount == 1000000
        assert swap.quote_mint == WSOL_MINT
        assert swap.quote_amount == 500000000

    def test_infer_no_swap(self):
        """Test that non-swap transactions return None."""
        token_deltas = {
            ("user", "token_a"): 100,
            ("user", "token_b"): 100,  # Both positive, no clear swap
        }
        sol_deltas = {}
        candidates = {"user"}

        swap = self.inference.infer_swap(token_deltas, sol_deltas, candidates)

        assert swap is None

    def test_confidence_reduction_multi_token(self):
        """Test confidence is reduced for multi-token swaps."""
        token_deltas = {
            ("user", "token_a"): 1000,
            ("user", "token_b"): 500,  # Multiple tokens received
        }
        sol_deltas = {
            "user": -500000000,
        }
        candidates = {"user"}

        swap = self.inference.infer_swap(token_deltas, sol_deltas, candidates)

        # Should still detect but with lower confidence
        assert swap is not None
        assert swap.confidence < 1.0

    def test_venue_identification(self):
        """Test venue identification from program IDs."""
        jupiter_programs = {"JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"}
        raydium_programs = {"675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"}
        pump_programs = {"6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"}

        assert self.inference.identify_venue(jupiter_programs) == "jupiter"
        assert self.inference.identify_venue(raydium_programs) == "raydium"
        assert self.inference.identify_venue(pump_programs) == "pump"
        assert self.inference.identify_venue(set()) == "unknown"
