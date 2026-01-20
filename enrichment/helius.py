"""Helius API client with credit budget management."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

# Helius credit costs
CREDIT_COSTS = {
    "getAccountInfo": 1,
    "getSignaturesForAddress": 10,
    "getTransaction": 10,
    "getTransactionsForAddress": 100,
}


@dataclass
class TransactionInfo:
    """Simplified transaction info from Helius."""
    signature: str
    slot: int
    block_time: int
    fee_payer: str
    success: bool
    fee: int


class CreditBucket:
    """
    Daily credit budget management.

    Tracks Helius API credit usage and enforces daily limits
    to prevent overspending.
    """

    def __init__(self, daily_limit: Optional[int] = None):
        self.daily_limit = daily_limit or settings.helius_daily_credit_limit
        self.used_today = 0
        self.last_reset = date.today()

    def _maybe_reset(self):
        """Reset counter if day changed."""
        today = date.today()
        if today != self.last_reset:
            logger.info(f"Credit bucket reset: used {self.used_today} yesterday")
            self.used_today = 0
            self.last_reset = today

    def can_spend(self, credits: int) -> bool:
        """Check if we have budget for this spend."""
        self._maybe_reset()
        return self.used_today + credits <= self.daily_limit

    def spend(self, credits: int) -> bool:
        """
        Attempt to spend credits.

        Returns True if successful, False if would exceed budget.
        """
        self._maybe_reset()

        if self.used_today + credits > self.daily_limit:
            return False

        self.used_today += credits
        return True

    def is_degraded(self) -> bool:
        """Check if we're running low on budget (>80% used)."""
        self._maybe_reset()
        return self.used_today > self.daily_limit * 0.8

    def get_remaining(self) -> int:
        """Get remaining credits for today."""
        self._maybe_reset()
        return max(0, self.daily_limit - self.used_today)

    def get_stats(self) -> dict:
        """Get credit bucket statistics."""
        self._maybe_reset()
        return {
            "daily_limit": self.daily_limit,
            "used_today": self.used_today,
            "remaining": self.get_remaining(),
            "usage_pct": self.used_today / self.daily_limit * 100,
            "is_degraded": self.is_degraded(),
        }


class HeliusClient:
    """
    Helius API client for wallet enrichment.

    Provides methods for:
    - Getting wallet transaction signatures
    - Fetching transaction details
    - Tracing wallet funding sources

    Uses CreditBucket to manage daily budget.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        credit_bucket: Optional[CreditBucket] = None,
        max_concurrent: int = 5,
    ):
        self.api_key = api_key or settings.helius_api_key
        self.base_url = f"https://mainnet.helius-rpc.com/?api-key={self.api_key}"
        self.credit_bucket = credit_bucket or CreditBucket()
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._http_client: Optional[httpx.AsyncClient] = None

        # Stats
        self._requests = 0
        self._errors = 0

    async def start(self):
        """Start the Helius client."""
        self._http_client = httpx.AsyncClient(timeout=30.0)
        logger.info("Helius client started")

    async def stop(self):
        """Stop the Helius client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        logger.info("Helius client stopped")

    async def _rpc_call(
        self,
        method: str,
        params: List[Any],
        credits: int,
    ) -> Optional[Any]:
        """Make an RPC call with credit budget check."""
        if not self.credit_bucket.can_spend(credits):
            logger.warning(f"Credit budget exceeded, skipping {method}")
            return None

        async with self._semaphore:
            try:
                self._requests += 1
                self.credit_bucket.spend(credits)

                payload = {
                    "jsonrpc": "2.0",
                    "id": self._requests,
                    "method": method,
                    "params": params,
                }

                response = await self._http_client.post(self.base_url, json=payload)
                response.raise_for_status()

                data = response.json()

                if "error" in data:
                    logger.error(f"RPC error: {data['error']}")
                    self._errors += 1
                    return None

                return data.get("result")

            except Exception as e:
                self._errors += 1
                logger.error(f"Helius API error ({method}): {e}")
                return None

    async def get_signatures(
        self,
        address: str,
        limit: int = 10,
        before: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get transaction signatures for an address.

        Cost: 10 credits per call.
        """
        params = [
            address,
            {"limit": limit}
        ]
        if before:
            params[1]["before"] = before

        result = await self._rpc_call(
            "getSignaturesForAddress",
            params,
            credits=CREDIT_COSTS["getSignaturesForAddress"]
        )

        return result or []

    async def get_transaction(
        self,
        signature: str,
        max_supported_version: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """
        Get transaction details.

        Cost: 10 credits per call.
        """
        params = [
            signature,
            {
                "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": max_supported_version,
            }
        ]

        return await self._rpc_call(
            "getTransaction",
            params,
            credits=CREDIT_COSTS["getTransaction"]
        )

    async def get_transactions_for_address(
        self,
        address: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get full transactions for an address.

        Cost: 100 credits per call - use sparingly!
        """
        # This is the expensive call - only use for confirmed suspicious wallets
        params = [
            address,
            {"limit": limit}
        ]

        # Note: This is a Helius-specific enhanced endpoint
        result = await self._rpc_call(
            "getTransactionsForAddress",
            params,
            credits=CREDIT_COSTS["getTransactionsForAddress"]
        )

        return result or []

    async def trace_funding(
        self,
        address: str,
        max_hops: int = 2,
    ) -> Optional[Dict[str, Any]]:
        """
        Trace wallet funding source (1-2 hops).

        Returns funding info or None if unable to trace.
        """
        if not self.credit_bucket.can_spend(10 * max_hops):
            return None

        current_address = address
        funding_chain = []

        for hop in range(max_hops):
            # Get first few transactions
            sigs = await self.get_signatures(current_address, limit=5)
            if not sigs:
                break

            # Look for the earliest transaction (potential funding)
            for sig_info in reversed(sigs):
                if sig_info.get("err") is None:
                    # Get transaction details
                    tx = await self.get_transaction(sig_info["signature"])
                    if tx:
                        # Find SOL transfer to this address
                        funder = self._extract_funder(tx, current_address)
                        if funder and funder != current_address:
                            funding_chain.append({
                                "hop": hop + 1,
                                "funder": funder,
                                "signature": sig_info["signature"],
                                "slot": sig_info.get("slot"),
                            })
                            current_address = funder
                            break

        if funding_chain:
            return {
                "wallet": address,
                "funding_chain": funding_chain,
                "ultimate_funder": funding_chain[-1]["funder"],
                "hops": len(funding_chain),
            }

        return None

    def _extract_funder(
        self,
        tx: Dict[str, Any],
        recipient: str
    ) -> Optional[str]:
        """Extract funder address from a transaction."""
        try:
            meta = tx.get("meta", {})
            message = tx.get("transaction", {}).get("message", {})
            account_keys = message.get("accountKeys", [])

            # Get pre/post balances
            pre_balances = meta.get("preBalances", [])
            post_balances = meta.get("postBalances", [])

            # Find who sent SOL to recipient
            for i, key in enumerate(account_keys):
                addr = key if isinstance(key, str) else key.get("pubkey", "")
                if addr == recipient:
                    # Check if balance increased
                    if i < len(pre_balances) and i < len(post_balances):
                        if post_balances[i] > pre_balances[i]:
                            # Find who decreased
                            for j, other_key in enumerate(account_keys):
                                other_addr = other_key if isinstance(other_key, str) else other_key.get("pubkey", "")
                                if j < len(pre_balances) and j < len(post_balances):
                                    if pre_balances[j] > post_balances[j]:
                                        return other_addr
        except Exception as e:
            logger.debug(f"Error extracting funder: {e}")

        return None

    async def get_token_metadata(self, mint: str) -> Optional[Dict[str, Any]]:
        """Get token metadata (name, symbol, etc.)."""
        # Use getAccountInfo for token metadata
        result = await self._rpc_call(
            "getAccountInfo",
            [mint, {"encoding": "jsonParsed"}],
            credits=CREDIT_COSTS["getAccountInfo"]
        )

        if result and result.get("value"):
            data = result["value"].get("data", {})
            if isinstance(data, dict) and "parsed" in data:
                return data["parsed"].get("info", {})

        return None

    def is_degraded(self) -> bool:
        """Check if enrichment is degraded due to budget."""
        return self.credit_bucket.is_degraded()

    def get_stats(self) -> dict:
        """Get client statistics."""
        return {
            "requests": self._requests,
            "errors": self._errors,
            "error_rate_pct": (
                self._errors / self._requests * 100
                if self._requests > 0
                else 0
            ),
            "credits": self.credit_bucket.get_stats(),
        }
