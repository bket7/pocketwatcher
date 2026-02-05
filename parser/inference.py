"""Swap inference from balance deltas."""

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from models.events import SwapCandidate, SwapSide
from .deltas import (
    DeltaBuilder,
    WSOL_MINT,
    QUOTE_MINTS,
    ATA_RENT_LAMPORTS,
)

logger = logging.getLogger(__name__)

# Venue identification by program ID
VENUE_PROGRAMS = {
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P": "pump",
    "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA": "pump",
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": "jupiter",
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": "raydium",
    "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C": "raydium",
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK": "raydium",
    "routeUGWgWzqBWFcrCfv8tritsqukccJPu3q5GPP3xS": "raydium",
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc": "orca",
    "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo": "meteora",
}


class SwapInference:
    """
    Infers swap events from balance deltas.

    Uses the balance-delta inference algorithm to detect:
    - BUY: user spent quote (SOL/USDC/USDT), received token
    - SELL: user spent token, received quote

    Assigns confidence based on data quality.
    """

    def __init__(self, delta_builder: Optional[DeltaBuilder] = None):
        self.delta_builder = delta_builder or DeltaBuilder()

        # Stats
        self._processed = 0
        self._swaps_found = 0
        self._confidence_sum = 0.0

    def infer_swap(
        self,
        token_deltas: Dict[Tuple[str, str], int],
        sol_deltas: Dict[str, int],
        candidates: Set[str]
    ) -> Optional[SwapCandidate]:
        """
        Infer swap from deltas.

        For each candidate:
        - Find largest NEGATIVE quote delta (spent)
        - Find largest POSITIVE non-quote delta (received)
        That pair = BUY. Reverse = SELL.

        Returns:
            SwapCandidate if swap detected with confidence >= threshold
        """
        self._processed += 1

        # Merge WSOL into SOL for unified quote handling
        merged_sol = self.delta_builder.normalize_wsol_to_sol(token_deltas, sol_deltas)

        # Pre-group token deltas by owner to avoid N*M scans
        owner_token_deltas: Dict[str, Dict[Tuple[str, str], int]] = {}
        for (owner, mint), amt in token_deltas.items():
            if mint == WSOL_MINT:
                continue
            owner_map = owner_token_deltas.get(owner)
            if owner_map is None:
                owner_map = {}
                owner_token_deltas[owner] = owner_map
            owner_map[(owner, mint)] = amt

        best_swap: Optional[SwapCandidate] = None
        best_confidence = 0.0

        for user in candidates:
            # Token deltas for this user (excluding WSOL)
            user_token_deltas = owner_token_deltas.get(user, {})

            # SOL/WSOL delta for this user (merged)
            user_sol_delta = merged_sol.get(user, 0)

            # --- Check for BUY (spent quote, received token) ---
            buy_swap = self._check_buy(
                user, user_token_deltas, user_sol_delta, sol_deltas.get(user)
            )
            if buy_swap and buy_swap.confidence > best_confidence:
                best_confidence = buy_swap.confidence
                best_swap = buy_swap

            # --- Check for SELL (spent token, received quote) ---
            sell_swap = self._check_sell(
                user, user_token_deltas, user_sol_delta, sol_deltas.get(user)
            )
            if sell_swap and sell_swap.confidence > best_confidence:
                best_confidence = sell_swap.confidence
                best_swap = sell_swap

        if best_swap:
            self._swaps_found += 1
            self._confidence_sum += best_swap.confidence

        return best_swap

    def _check_buy(
        self,
        user: str,
        user_token_deltas: Dict[Tuple[str, str], int],
        user_sol_delta: int,
        lamports_delta: Optional[int]
    ) -> Optional[SwapCandidate]:
        """Check for BUY pattern: spent quote, received token."""
        quote_spent: List[Tuple[str, int]] = []
        token_received: List[Tuple[str, int]] = []

        # Check SOL/WSOL spent (negative merged delta)
        if user_sol_delta < 0:
            quote_spent.append((WSOL_MINT, user_sol_delta))

        # Check USDC/USDT spent
        for (o, m), amt in user_token_deltas.items():
            if m in QUOTE_MINTS and amt < 0:
                quote_spent.append((m, amt))

        # Check non-quote tokens received
        for (o, m), amt in user_token_deltas.items():
            if m not in QUOTE_MINTS and amt > 0:
                token_received.append((m, amt))

        if not quote_spent or not token_received:
            return None

        # Pick the largest quote spent and token received
        quote_mint, quote_amt = max(quote_spent, key=lambda x: abs(x[1]))
        token_mint, token_amt = max(token_received, key=lambda x: x[1])

        confidence = self._calculate_confidence(
            user_token_deltas, quote_spent, token_received, lamports_delta
        )

        return SwapCandidate(
            user_wallet=user,
            side=SwapSide.BUY,
            base_mint=token_mint,
            base_amount=token_amt,
            quote_mint=quote_mint,
            quote_amount=abs(quote_amt),
            confidence=confidence,
        )

    def _check_sell(
        self,
        user: str,
        user_token_deltas: Dict[Tuple[str, str], int],
        user_sol_delta: int,
        lamports_delta: Optional[int]
    ) -> Optional[SwapCandidate]:
        """Check for SELL pattern: spent token, received quote."""
        token_sold: List[Tuple[str, int]] = []
        quote_received: List[Tuple[str, int]] = []

        # Check non-quote tokens sold (negative)
        for (o, m), amt in user_token_deltas.items():
            if m not in QUOTE_MINTS and amt < 0:
                token_sold.append((m, amt))

        # Check SOL/WSOL received (positive merged delta)
        if user_sol_delta > 0:
            quote_received.append((WSOL_MINT, user_sol_delta))

        # Check USDC/USDT received
        for (o, m), amt in user_token_deltas.items():
            if m in QUOTE_MINTS and amt > 0:
                quote_received.append((m, amt))

        if not token_sold or not quote_received:
            return None

        # Pick the largest token sold and quote received
        token_mint, token_amt = max(token_sold, key=lambda x: abs(x[1]))
        quote_mint, quote_amt = max(quote_received, key=lambda x: x[1])

        confidence = self._calculate_confidence(
            user_token_deltas, quote_received, token_sold, lamports_delta
        )

        return SwapCandidate(
            user_wallet=user,
            side=SwapSide.SELL,
            base_mint=token_mint,
            base_amount=abs(token_amt),
            quote_mint=quote_mint,
            quote_amount=quote_amt,
            confidence=confidence,
        )

    def _calculate_confidence(
        self,
        user_deltas: Dict[Tuple[str, str], int],
        quote_deltas: List[Tuple[str, int]],
        token_deltas: List[Tuple[str, int]],
        lamports_delta: Optional[int] = None
    ) -> float:
        """
        Calculate confidence score for swap inference.

        Start at 1.0, subtract for each uncertainty factor.
        """
        confidence = 1.0

        # Multiple non-quote mints involved (multi-hop or multi-token swap)
        if len(token_deltas) > 1:
            confidence -= 0.2

        # No quote delta detected
        if len(quote_deltas) == 0:
            confidence -= 0.2

        # Multiple quote mints involved
        if len(quote_deltas) > 1:
            confidence -= 0.1

        # ATA creation detected (potential rent confusion)
        if lamports_delta and abs(lamports_delta) == ATA_RENT_LAMPORTS:
            confidence -= 0.1

        # Many token changes for same user (complex tx)
        if len(user_deltas) > 3:
            confidence -= 0.1

        return max(confidence, 0.0)

    def identify_venue(self, programs_invoked: Set[str]) -> str:
        """Identify trading venue from invoked programs."""
        for prog_id in programs_invoked:
            if prog_id in VENUE_PROGRAMS:
                return VENUE_PROGRAMS[prog_id]
        return "unknown"

    def estimate_route_depth(self, programs_invoked: Set[str]) -> int:
        """Estimate routing depth from program count."""
        venue_count = sum(1 for p in programs_invoked if p in VENUE_PROGRAMS)
        return max(1, venue_count)

    def get_stats(self) -> dict:
        """Get inference statistics."""
        avg_confidence = (
            self._confidence_sum / self._swaps_found
            if self._swaps_found > 0
            else 0.0
        )
        detection_rate = (
            self._swaps_found / self._processed * 100
            if self._processed > 0
            else 0.0
        )

        return {
            "processed": self._processed,
            "swaps_found": self._swaps_found,
            "detection_rate_pct": detection_rate,
            "avg_confidence": avg_confidence,
        }


def process_transaction(
    tx_data: Dict[str, Any],
    delta_builder: DeltaBuilder,
    inference: SwapInference,
) -> Tuple[Set[str], Optional[SwapCandidate], str, Set[str]]:
    """
    Process a single transaction.

    Returns:
        Tuple of (mints_touched, swap_candidate, venue, programs_invoked)
    """
    # Build deltas
    token_deltas, sol_deltas = delta_builder.build_deltas(tx_data)

    # Extract metadata
    fee_payer = tx_data.get("fee_payer", "")
    if not fee_payer:
        account_keys = tx_data.get("account_keys", [])
        fee_payer = account_keys[0] if account_keys else ""

    mints_touched = delta_builder.extract_mints_touched(token_deltas)
    programs_invoked = delta_builder.extract_program_ids(tx_data)

    # Infer swap
    candidates = delta_builder.get_candidate_users(token_deltas, fee_payer)
    swap = inference.infer_swap(token_deltas, sol_deltas, candidates)

    # Identify venue
    venue = inference.identify_venue(programs_invoked)

    return mints_touched, swap, venue, programs_invoked
