"""
Refresh GMGN Auth - Opens browser for manual login to refresh cookies.
"""

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright


AUTH_PATH = Path("C:/Users/Administrator/Desktop/Projects/sauron/data/auth/gmgn_storage_state.json")


async def refresh_auth(wait_seconds: int = 60):
    """Open browser for manual GMGN login."""
    print("\n" + "="*60)
    print(" GMGN Auth Refresh")
    print("="*60)
    print(f"\n1. A browser will open to gmgn.ai")
    print("2. Log in with Twitter/wallet if needed")
    print(f"3. You have {wait_seconds} seconds to complete login")
    print("4. Auth will be saved automatically")
    print("\n" + "="*60 + "\n")

    async with async_playwright() as p:
        # Launch visible browser
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        # Go to GMGN
        print("Opening GMGN...")
        await page.goto("https://gmgn.ai/sol", wait_until="domcontentloaded", timeout=60000)

        print(f"\nBrowser opened. You have {wait_seconds} seconds to log in...")
        print("Waiting for login...")

        # Wait for user to complete login
        for i in range(wait_seconds, 0, -10):
            print(f"  {i} seconds remaining...")
            await asyncio.sleep(10)

        print("\nTime's up! Saving auth state...")

        # Save auth state
        state = await context.storage_state()
        state['_saved_at'] = str(asyncio.get_event_loop().time())

        AUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(AUTH_PATH, 'w') as f:
            json.dump(state, f, indent=2)

        print(f"\nAuth saved to {AUTH_PATH}")
        print(f"Cookies: {len(state.get('cookies', []))}")

        await browser.close()

    # Test the new auth
    print("\nTesting new auth...")
    await test_auth()


async def test_auth():
    """Test if auth works."""
    if not AUTH_PATH.exists():
        print("No auth file found!")
        return False

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(storage_state=str(AUTH_PATH))
        page = await context.new_page()

        # Navigate to establish session
        await page.goto("https://gmgn.ai/sol", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        # Try API call
        test_mint = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"  # POPCAT
        url = f"https://gmgn.ai/defi/quotation/v1/tokens/sol/{test_mint}"

        result = await page.evaluate("""
            async (url) => {
                try {
                    const resp = await fetch(url, {
                        credentials: 'include',
                        headers: { 'Accept': 'application/json' }
                    });
                    if (resp.status === 200) {
                        const data = await resp.json();
                        return { success: true, data: data };
                    }
                    return { success: false, status: resp.status };
                } catch (e) {
                    return { success: false, error: e.message };
                }
            }
        """, url)

        await browser.close()

        if result.get("success"):
            token = result.get("data", {}).get("data", {}).get("token", {})
            print(f"SUCCESS! Got token: {token.get('symbol')} @ ${token.get('price')}")
            return True
        else:
            print(f"FAILED: {result}")
            return False


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Refresh GMGN auth cookies")
    parser.add_argument("--wait", type=int, default=60, help="Seconds to wait for login (default: 60)")
    args = parser.parse_args()
    asyncio.run(refresh_auth(wait_seconds=args.wait))
