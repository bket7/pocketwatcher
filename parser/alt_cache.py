"""Address Lookup Table (ALT) cache for Jupiter v6 transactions."""

import asyncio
import logging
import struct
from typing import Dict, List, Optional

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)


class ALTCache:
    """
    Cache for Address Lookup Table (ALT) resolution.

    Jupiter v6 uses versioned transactions with ALTs. Most meme trading
    goes through Jupiter, so we need to resolve ALT addresses.

    Expected: Yellowstone provides resolved addresses in meta.
    Fallback: Fetch ALT content via RPC (1 credit per lookup on Helius).
    """

    def __init__(
        self,
        rpc_url: Optional[str] = None,
        cache_size: int = 10000,
    ):
        self.rpc_url = rpc_url or settings.helius_endpoint
        self._cache: Dict[str, List[str]] = {}
        self._cache_size = cache_size
        self._hits = 0
        self._misses = 0
        self._fetches = 0
        self._fetch_errors = 0
        self._http_client: Optional[httpx.AsyncClient] = None

    async def start(self):
        """Start the ALT cache with HTTP client."""
        self._http_client = httpx.AsyncClient(timeout=30.0)
        logger.info("ALT cache started")

    async def stop(self):
        """Stop the ALT cache."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        logger.info("ALT cache stopped")

    def get_all_accounts(
        self,
        account_keys: List[str],
        loaded_writable_addresses: Optional[List[str]] = None,
        loaded_readonly_addresses: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Reconstruct full account list including ALT-resolved addresses.

        Yellowstone meta should include loadedAddresses. This method
        combines static keys with loaded addresses.
        """
        accounts = list(account_keys)

        if loaded_writable_addresses:
            accounts.extend(loaded_writable_addresses)
        if loaded_readonly_addresses:
            accounts.extend(loaded_readonly_addresses)

        return accounts

    async def resolve(self, alt_address: str) -> List[str]:
        """
        Resolve an ALT to its contained addresses.

        Args:
            alt_address: Address Lookup Table account address

        Returns:
            List of addresses contained in the ALT
        """
        # Check cache first
        if alt_address in self._cache:
            self._hits += 1
            return self._cache[alt_address]

        self._misses += 1

        # Fetch from RPC
        try:
            addresses = await self._fetch_alt(alt_address)
            self._fetches += 1

            # Cache the result
            if len(self._cache) >= self._cache_size:
                # Simple LRU: remove oldest entries
                to_remove = list(self._cache.keys())[:len(self._cache) // 10]
                for key in to_remove:
                    del self._cache[key]

            self._cache[alt_address] = addresses
            return addresses

        except Exception as e:
            self._fetch_errors += 1
            logger.error(f"Failed to fetch ALT {alt_address}: {e}")
            return []

    async def _fetch_alt(self, alt_address: str) -> List[str]:
        """Fetch ALT content from RPC."""
        if not self._http_client:
            raise RuntimeError("ALT cache not started")

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getAccountInfo",
            "params": [
                alt_address,
                {"encoding": "base64"}
            ]
        }

        response = await self._http_client.post(self.rpc_url, json=payload)
        response.raise_for_status()

        data = response.json()

        if "error" in data:
            raise Exception(f"RPC error: {data['error']}")

        result = data.get("result", {})
        value = result.get("value")

        if not value:
            logger.warning(f"ALT {alt_address} not found")
            return []

        # Decode base64 data
        import base64
        account_data = base64.b64decode(value["data"][0])

        # Parse ALT data structure
        addresses = self._parse_alt_data(account_data)
        return addresses

    def _parse_alt_data(self, data: bytes) -> List[str]:
        """
        Parse ALT account data to extract addresses.

        ALT format (simplified):
        - 8 bytes: discriminator
        - 8 bytes: deactivation slot (u64)
        - 8 bytes: last extended slot (u64)
        - 1 byte: last extended slot start index (u8)
        - 1 byte: has authority flag
        - 32 bytes: authority (if has_authority)
        - remaining: addresses (each 32 bytes)
        """
        import base58

        addresses = []

        try:
            # Skip header (variable size based on authority)
            # Minimum header is 26 bytes for AddressLookupTable
            if len(data) < 56:
                return addresses

            # The addresses start after the header
            # For simplicity, we'll find the address section
            # by looking for valid base58 addresses

            # Skip the first 56 bytes (metadata)
            addr_data = data[56:]

            # Each address is 32 bytes
            for i in range(0, len(addr_data), 32):
                if i + 32 > len(addr_data):
                    break
                addr_bytes = addr_data[i:i+32]
                # Convert to base58
                address = base58.b58encode(addr_bytes).decode()
                addresses.append(address)

        except Exception as e:
            logger.error(f"Failed to parse ALT data: {e}")

        return addresses

    async def prefetch(self, alt_addresses: List[str]):
        """Prefetch multiple ALTs in parallel."""
        tasks = [self.resolve(addr) for addr in alt_addresses]
        await asyncio.gather(*tasks, return_exceptions=True)

    def get_stats(self) -> dict:
        """Get cache statistics."""
        total_requests = self._hits + self._misses
        hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0

        return {
            "cache_size": len(self._cache),
            "max_cache_size": self._cache_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate_pct": hit_rate,
            "fetches": self._fetches,
            "fetch_errors": self._fetch_errors,
        }

    def clear_cache(self):
        """Clear the cache."""
        self._cache.clear()
