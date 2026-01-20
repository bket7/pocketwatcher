"""Balance delta extraction from transactions."""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Constants
WSOL_MINT = "So11111111111111111111111111111111111111112"
ATA_RENT_LAMPORTS = 2039280  # ~0.00203 SOL for ATA creation
ACCOUNT_RENT_LAMPORTS = 890880  # ~0.00089 SOL for basic account

# Quote mints for swap detection
QUOTE_MINTS = {
    "So11111111111111111111111111111111111111112",  # WSOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
}


@dataclass
class TokenBalance:
    """Token balance from transaction metadata."""
    owner: str
    mint: str
    amount: int
    decimals: int = 9


class DeltaBuilder:
    """
    Builds balance deltas from transaction data.

    Handles:
    - Token balance changes (pre/post token balances)
    - SOL balance changes (pre/post lamport balances)
    - Transaction fee correction
    - ATA rent correction
    - WSOL/SOL normalization
    """

    def __init__(self):
        self._processed = 0
        self._errors = 0

    def build_deltas(
        self,
        tx_data: Dict[str, Any],
    ) -> Tuple[Dict[Tuple[str, str], int], Dict[str, int]]:
        """
        Build token and SOL deltas from transaction data.

        Args:
            tx_data: Transaction data dict with pre/post balances

        Returns:
            Tuple of (token_deltas, sol_deltas) where:
            - token_deltas: {(owner, mint): net_amount}
            - sol_deltas: {account: net_lamports} (after fee/rent adjustment)
        """
        self._processed += 1
        token_deltas: Dict[Tuple[str, str], int] = {}
        sol_deltas: Dict[str, int] = {}

        try:
            # Extract fee payer (first account key)
            account_keys = tx_data.get("account_keys", [])
            fee_payer = account_keys[0] if account_keys else tx_data.get("fee_payer", "")
            tx_fee = tx_data.get("fee", 0)

            # --- Token deltas from preTokenBalances vs postTokenBalances ---
            pre_balances = self._parse_token_balances(
                tx_data.get("pre_token_balances", [])
            )
            post_balances = self._parse_token_balances(
                tx_data.get("post_token_balances", [])
            )

            # Build delta map
            all_keys = set(pre_balances.keys()) | set(post_balances.keys())
            for key in all_keys:
                pre_amt = pre_balances.get(key, 0)
                post_amt = post_balances.get(key, 0)
                delta = post_amt - pre_amt
                if delta != 0:
                    token_deltas[key] = delta

            # --- SOL deltas (lamports) with fee/rent correction ---
            pre_sol = tx_data.get("pre_balances", {})
            post_sol = tx_data.get("post_balances", {})

            # Handle both dict and list formats
            if isinstance(pre_sol, list) and account_keys:
                pre_sol = dict(zip(account_keys, pre_sol))
            if isinstance(post_sol, list) and account_keys:
                post_sol = dict(zip(account_keys, post_sol))

            all_accounts = set(pre_sol.keys()) | set(post_sol.keys())
            accounts_created = 0

            for account in all_accounts:
                pre_lamports = pre_sol.get(account, 0)
                post_lamports = post_sol.get(account, 0)
                delta = post_lamports - pre_lamports

                # Add back tx fee for fee payer
                if account == fee_payer:
                    delta += tx_fee

                # Detect ATA creation rent
                if pre_lamports == 0 and post_lamports > 0:
                    accounts_created += 1
                    # If exactly rent amount, skip (pure rent transfer)
                    if post_lamports in (ATA_RENT_LAMPORTS, ACCOUNT_RENT_LAMPORTS):
                        continue
                    # Otherwise subtract rent from delta
                    delta -= ATA_RENT_LAMPORTS

                if delta != 0:
                    sol_deltas[account] = delta

        except Exception as e:
            self._errors += 1
            logger.error(f"Error building deltas: {e}")

        return token_deltas, sol_deltas

    def _parse_token_balances(
        self,
        balances: List[Any]
    ) -> Dict[Tuple[str, str], int]:
        """Parse token balances into (owner, mint) -> amount map."""
        result = {}

        for b in balances:
            if isinstance(b, dict):
                owner = b.get("owner", "")
                mint = b.get("mint", "")
                # Handle nested ui_token_amount or direct amount
                amount_data = b.get("ui_token_amount", b)
                if isinstance(amount_data, dict):
                    amount = int(amount_data.get("amount", 0))
                else:
                    amount = int(b.get("amount", 0))
            elif hasattr(b, "owner"):
                # Protobuf-style object
                owner = b.owner
                mint = b.mint
                if hasattr(b, "ui_token_amount"):
                    amount = int(b.ui_token_amount.amount)
                else:
                    amount = int(getattr(b, "amount", 0))
            else:
                continue

            if owner and mint:
                result[(owner, mint)] = amount

        return result

    def normalize_wsol_to_sol(
        self,
        token_deltas: Dict[Tuple[str, str], int],
        sol_deltas: Dict[str, int]
    ) -> Dict[str, int]:
        """
        Merge WSOL token deltas into SOL deltas for unified quote handling.

        WSOL is just wrapped SOL - treat them as equivalent.
        """
        merged = sol_deltas.copy()

        for (owner, mint), amount in token_deltas.items():
            if mint == WSOL_MINT:
                merged[owner] = merged.get(owner, 0) + amount

        return merged

    def get_candidate_users(
        self,
        token_deltas: Dict[Tuple[str, str], int],
        fee_payer: str
    ) -> Set[str]:
        """Get candidate user wallets for swap detection."""
        candidates = {fee_payer}

        for (owner, mint), amount in token_deltas.items():
            if abs(amount) > 0:
                candidates.add(owner)

        return candidates

    def extract_mints_touched(
        self,
        token_deltas: Dict[Tuple[str, str], int]
    ) -> Set[str]:
        """Extract all non-WSOL mints touched in the transaction."""
        mints = set()
        for (owner, mint) in token_deltas.keys():
            if mint != WSOL_MINT:
                mints.add(mint)
        return mints

    def extract_program_ids(self, tx_data: Dict[str, Any]) -> Set[str]:
        """Extract all program IDs invoked in the transaction."""
        programs = set()

        # From inner instructions
        for inner in tx_data.get("inner_instructions", []):
            for inst in inner.get("instructions", []):
                prog_id = inst.get("program_id", "")
                if prog_id:
                    programs.add(prog_id)

        # From top-level instructions
        for inst in tx_data.get("instructions", []):
            prog_id = inst.get("program_id", "")
            if prog_id:
                programs.add(prog_id)

        # From explicit programs_invoked field (mock data)
        programs.update(tx_data.get("programs_invoked", []))

        return programs

    def get_stats(self) -> dict:
        """Get builder statistics."""
        return {
            "processed": self._processed,
            "errors": self._errors,
            "error_rate_pct": (self._errors / self._processed * 100) if self._processed > 0 else 0,
        }
