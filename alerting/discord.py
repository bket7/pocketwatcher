"""Discord webhook alerting."""

import asyncio
import logging
from typing import Optional

import httpx

from config.settings import settings
from models.profiles import Alert
from enrichment.scoring import CTOScore
from .formatter import AlertFormatter

logger = logging.getLogger(__name__)


class DiscordAlerter:
    """
    Discord webhook alerter.

    Sends formatted alerts to a Discord channel via webhook.
    Includes rate limiting and retry logic.
    """

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        rate_limit_per_minute: int = 30,
    ):
        self.webhook_url = webhook_url or settings.discord_webhook_url
        self.rate_limit = rate_limit_per_minute
        self._http_client: Optional[httpx.AsyncClient] = None
        self._semaphore = asyncio.Semaphore(5)
        self._sent_count = 0
        self._error_count = 0
        self._last_reset = 0
        self._minute_count = 0

    async def start(self):
        """Start the Discord alerter."""
        if not self.webhook_url:
            logger.warning("Discord webhook URL not configured")
            return

        self._http_client = httpx.AsyncClient(timeout=30.0)
        logger.info("Discord alerter started")

    async def stop(self):
        """Stop the Discord alerter."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        logger.info("Discord alerter stopped")

    async def send_alert(
        self,
        alert: Alert,
        cto_score: Optional[CTOScore] = None,
    ) -> bool:
        """
        Send an alert to Discord.

        Returns True if successful. Retries with exponential backoff on
        transient failures (network errors, 5xx responses).
        """
        if not self.webhook_url or not self._http_client:
            return False

        # Rate limiting
        if not self._check_rate_limit():
            logger.warning("Discord rate limit reached, skipping alert")
            return False

        # Format the message
        payload = AlertFormatter.format_discord_embed(alert, cto_score)

        max_retries = 3
        retry_delays = [1, 2, 4]  # exponential backoff

        async with self._semaphore:
            for attempt in range(max_retries):
                try:
                    response = await self._http_client.post(
                        self.webhook_url,
                        json=payload
                    )

                    if response.status_code == 429:
                        # Rate limited by Discord
                        retry_after = response.json().get("retry_after", 5)
                        logger.warning(f"Discord rate limited, retry after {retry_after}s")
                        await asyncio.sleep(retry_after)
                        continue

                    if response.status_code >= 500:
                        # Server error - retry
                        if attempt < max_retries - 1:
                            logger.warning(f"Discord server error {response.status_code}, retrying in {retry_delays[attempt]}s")
                            await asyncio.sleep(retry_delays[attempt])
                            continue
                        else:
                            self._error_count += 1
                            logger.error(f"Discord server error after {max_retries} attempts: {response.status_code}")
                            return False

                    response.raise_for_status()
                    self._sent_count += 1
                    logger.info(f"Discord alert sent for {alert.mint[:8]}")
                    return True

                except (httpx.ConnectError, httpx.TimeoutException) as e:
                    # Network errors - retry
                    if attempt < max_retries - 1:
                        logger.warning(f"Discord network error, retrying in {retry_delays[attempt]}s: {e}")
                        await asyncio.sleep(retry_delays[attempt])
                        continue
                    else:
                        self._error_count += 1
                        logger.error(f"Discord send failed after {max_retries} attempts: {e}")
                        return False
                except httpx.HTTPStatusError as e:
                    # Client errors (4xx except 429) - don't retry
                    self._error_count += 1
                    logger.error(f"Discord webhook error: {e.response.status_code}")
                    return False
                except Exception as e:
                    self._error_count += 1
                    logger.error(f"Discord send error: {e}")
                    return False

        return False

    def _check_rate_limit(self) -> bool:
        """Check if we're within rate limit."""
        import time

        now = int(time.time())
        minute = now // 60

        if minute != self._last_reset:
            self._last_reset = minute
            self._minute_count = 0

        if self._minute_count >= self.rate_limit:
            return False

        self._minute_count += 1
        return True

    async def send_test_message(self) -> bool:
        """Send a test message to verify webhook configuration."""
        if not self.webhook_url or not self._http_client:
            return False

        payload = {
            "content": "\U0001F916 Pocketwatcher connected and monitoring!"
        }

        try:
            response = await self._http_client.post(
                self.webhook_url,
                json=payload
            )
            response.raise_for_status()
            logger.info("Discord test message sent")
            return True
        except Exception as e:
            logger.error(f"Discord test failed: {e}")
            return False

    def is_configured(self) -> bool:
        """Check if Discord alerting is configured."""
        return bool(self.webhook_url)

    def get_stats(self) -> dict:
        """Get alerter statistics."""
        return {
            "configured": self.is_configured(),
            "sent_count": self._sent_count,
            "error_count": self._error_count,
            "error_rate_pct": (
                self._error_count / (self._sent_count + self._error_count) * 100
                if (self._sent_count + self._error_count) > 0
                else 0
            ),
        }
