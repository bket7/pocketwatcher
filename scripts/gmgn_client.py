"""
Token Price Client - Fetches token price/market cap data.

Uses DexScreener API as primary source (free, no auth required).
GMGN is available as a fallback but requires browser auth.
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx
from playwright.async_api import async_playwright, BrowserContext, Page


# GMGN auth state from sauron
SAURON_AUTH_STATE = Path("C:/Users/Administrator/Desktop/Projects/sauron/data/auth/gmgn_storage_state.json")

# Browser launcher service
LAUNCHER_URL = "http://localhost:3000"


def generate_gmgn_params() -> dict:
    """Generate required GMGN API query parameters."""
    device_id = str(uuid.uuid4())
    app_ver = datetime.now().strftime("%Y%m%d") + "-9790-e083a22"
    return {
        "device_id": device_id,
        "fp_did": "unknown",
        "client_id": f"gmgn_web_{app_ver}",
        "from_app": "gmgn",
        "app_ver": app_ver,
        "tz_name": "America/New_York",
        "tz_offset": "-18000",
        "app_lang": "en-US",
        "os": "web",
        "worker": "0",
    }


@dataclass
class TokenData:
    """Token price and market data."""
    mint: str
    price_usd: Optional[float] = None
    price_sol: Optional[float] = None
    market_cap_usd: Optional[float] = None
    market_cap_sol: Optional[float] = None
    liquidity_usd: Optional[float] = None
    volume_24h_usd: Optional[float] = None
    price_change_24h_pct: Optional[float] = None
    name: Optional[str] = None
    symbol: Optional[str] = None
    success: bool = False
    error: Optional[str] = None
    source: str = "unknown"


class DexScreenerClient:
    """
    DexScreener client for fetching token data.

    Uses the free DexScreener API - no auth required.
    This is the primary/recommended client.
    """

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._request_count = 0
        self._error_count = 0

    async def start(self):
        """Start the client."""
        self._client = httpx.AsyncClient(timeout=15.0)

    async def stop(self):
        """Stop the client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def get_token(self, mint: str) -> TokenData:
        """
        Fetch token data from DexScreener.

        Args:
            mint: Token mint address

        Returns:
            TokenData with price and market cap info
        """
        if not self._client:
            return TokenData(mint=mint, success=False, error="Client not started")

        try:
            resp = await self._client.get(f"https://api.dexscreener.com/latest/dex/tokens/{mint}")
            self._request_count += 1

            if resp.status_code == 200:
                data = resp.json()
                pairs = data.get("pairs", [])

                if not pairs:
                    return TokenData(
                        mint=mint,
                        success=False,
                        error="No pairs found",
                        source="dexscreener"
                    )

                # Get the most liquid Solana pair
                sol_pairs = [p for p in pairs if p.get("chainId") == "solana"]
                if not sol_pairs:
                    sol_pairs = pairs

                best = max(sol_pairs, key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0))

                return TokenData(
                    mint=mint,
                    price_usd=_safe_float(best.get("priceUsd")),
                    market_cap_usd=_safe_float(best.get("fdv")),  # fdv = fully diluted valuation
                    liquidity_usd=_safe_float(best.get("liquidity", {}).get("usd")),
                    volume_24h_usd=_safe_float(best.get("volume", {}).get("h24")),
                    price_change_24h_pct=_safe_float(best.get("priceChange", {}).get("h24")),
                    name=best.get("baseToken", {}).get("name"),
                    symbol=best.get("baseToken", {}).get("symbol"),
                    success=True,
                    source="dexscreener"
                )
            else:
                self._error_count += 1
                return TokenData(
                    mint=mint,
                    success=False,
                    error=f"HTTP {resp.status_code}",
                    source="dexscreener"
                )

        except Exception as e:
            self._error_count += 1
            return TokenData(mint=mint, success=False, error=str(e), source="dexscreener")

    async def get_tokens_batch(
        self,
        mints: list[str],
        delay: float = 0.3,
    ) -> Dict[str, TokenData]:
        """
        Fetch multiple tokens with rate limiting.

        Args:
            mints: List of token mint addresses
            delay: Delay between requests in seconds

        Returns:
            Dict mapping mint to TokenData
        """
        results = {}

        for mint in mints:
            results[mint] = await self.get_token(mint)
            if len(results) < len(mints):
                await asyncio.sleep(delay)

        return results

    @property
    def stats(self) -> Dict[str, int]:
        """Get client stats."""
        return {
            "requests": self._request_count,
            "errors": self._error_count,
        }


class GMGNClient:
    """
    GMGN client for fetching token data.

    Uses authenticated browser sessions via Playwright to bypass Cloudflare.
    Connects to sauron's browser-launcher service.
    """

    def __init__(self, auth_state_path: Optional[Path] = None):
        """
        Initialize client.

        Args:
            auth_state_path: Path to GMGN auth state JSON (default: sauron's state)
        """
        self.auth_state_path = auth_state_path or SAURON_AUTH_STATE
        self._playwright = None
        self._browser = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._initialized = False
        self._gmgn_params = generate_gmgn_params()
        self._request_count = 0
        self._error_count = 0

    async def start(self):
        """Start the client and connect to browser."""
        if not self.auth_state_path.exists():
            raise FileNotFoundError(
                f"GMGN auth state not found at {self.auth_state_path}. "
                "Ensure sauron's auth is configured."
            )

        self._playwright = await async_playwright().start()

        # Launch browser with auth state
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._context = await self._browser.new_context(
            storage_state=str(self.auth_state_path)
        )
        self._page = await self._context.new_page()

        # Navigate to GMGN to establish session
        await self._page.goto("https://gmgn.ai/sol", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)  # Let Cloudflare challenge complete

        self._initialized = True

    async def stop(self):
        """Stop the client and close browser."""
        if self._page:
            await self._page.close()
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

        self._initialized = False

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def _fetch_json(self, url: str) -> dict:
        """Fetch JSON using in-page JavaScript fetch (bypasses Cloudflare)."""
        if not self._initialized or not self._page:
            raise RuntimeError("Client not started")

        result = await self._page.evaluate("""
            async (url) => {
                try {
                    const response = await fetch(url, {
                        method: 'GET',
                        credentials: 'include',
                        headers: {
                            'Accept': 'application/json',
                        }
                    });
                    const status = response.status;
                    if (status === 200) {
                        const data = await response.json();
                        return { success: true, status: status, data: data };
                    } else {
                        const text = await response.text();
                        return { success: false, status: status, error: text.substring(0, 200) };
                    }
                } catch (e) {
                    return { success: false, status: 0, error: e.message };
                }
            }
        """, url)

        return result

    async def get_token(self, mint: str, timeout: float = 30.0) -> TokenData:
        """
        Fetch token data from GMGN.

        Args:
            mint: Token mint address
            timeout: Request timeout in seconds

        Returns:
            TokenData with price and market cap info
        """
        # Build URL
        base_url = f"https://gmgn.ai/defi/quotation/v1/tokens/sol/{mint}"
        params = self._gmgn_params
        query_string = urlencode(params)
        full_url = f"{base_url}?{query_string}"

        try:
            result = await asyncio.wait_for(
                self._fetch_json(full_url),
                timeout=timeout
            )

            self._request_count += 1

            if result.get("success"):
                data = result.get("data", {})
                token_data = data.get("data", {}).get("token", {})

                if not token_data:
                    return TokenData(
                        mint=mint,
                        success=False,
                        error="No token data in response"
                    )

                return TokenData(
                    mint=mint,
                    price_usd=_safe_float(token_data.get("price")),
                    price_sol=None,  # Calculate from price/SOL_price if needed
                    market_cap_usd=_safe_float(token_data.get("market_cap")),
                    market_cap_sol=None,
                    liquidity_usd=_safe_float(token_data.get("liquidity")),
                    volume_24h_usd=_safe_float(token_data.get("volume_24h")),
                    price_change_24h_pct=_safe_float(token_data.get("price_change_24h")),
                    name=token_data.get("name"),
                    symbol=token_data.get("symbol"),
                    success=True,
                )
            else:
                self._error_count += 1
                status = result.get("status", 0)
                error = result.get("error", "Unknown error")

                return TokenData(
                    mint=mint,
                    success=False,
                    error=f"HTTP {status}: {error}"
                )

        except asyncio.TimeoutError:
            self._error_count += 1
            return TokenData(mint=mint, success=False, error=f"Timeout after {timeout}s")
        except Exception as e:
            self._error_count += 1
            return TokenData(mint=mint, success=False, error=str(e))

    async def get_tokens_batch(
        self,
        mints: list[str],
        delay: float = 1.0,
        max_concurrent: int = 1
    ) -> Dict[str, TokenData]:
        """
        Fetch multiple tokens with rate limiting.

        Args:
            mints: List of token mint addresses
            delay: Delay between requests in seconds
            max_concurrent: Max concurrent requests (keep at 1 for safety)

        Returns:
            Dict mapping mint to TokenData
        """
        results = {}

        for mint in mints:
            results[mint] = await self.get_token(mint)
            if len(results) < len(mints):
                await asyncio.sleep(delay)

        return results

    @property
    def stats(self) -> Dict[str, int]:
        """Get client stats."""
        return {
            "requests": self._request_count,
            "errors": self._error_count,
        }


def _safe_float(value: Any) -> Optional[float]:
    """Safely convert value to float."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


async def main():
    """Test the token price clients."""
    # Test with a known token
    test_mint = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"  # POPCAT

    print(f"Testing DexScreener client with {test_mint}\n")

    async with DexScreenerClient() as client:
        result = await client.get_token(test_mint)

        if result.success:
            print(f"DexScreener: Success!")
            print(f"  Name: {result.name}")
            print(f"  Symbol: {result.symbol}")
            print(f"  Price: ${result.price_usd}")
            print(f"  Market Cap: ${result.market_cap_usd:,.0f}" if result.market_cap_usd else "  Market Cap: N/A")
        else:
            print(f"DexScreener: Failed - {result.error}")

    print("\nTesting GMGN client (may fail due to Cloudflare)...")

    try:
        async with GMGNClient() as client:
            result = await client.get_token(test_mint)

            if result.success:
                print(f"GMGN: Success!")
                print(f"  Name: {result.name}")
                print(f"  Symbol: {result.symbol}")
                print(f"  Price: ${result.price_usd}")
                print(f"  Market Cap: ${result.market_cap_usd:,.0f}" if result.market_cap_usd else "  Market Cap: N/A")
            else:
                print(f"GMGN: Failed - {result.error}")
    except Exception as e:
        print(f"GMGN: Error - {e}")


if __name__ == "__main__":
    asyncio.run(main())
