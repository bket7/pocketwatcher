"""Telegram bot alerting."""

import asyncio
import logging
from typing import Optional

import httpx

from config.settings import settings
from models.profiles import Alert
from enrichment.scoring import CTOScore
from .formatter import AlertFormatter

logger = logging.getLogger(__name__)


class TelegramAlerter:
    """
    Telegram bot alerter.

    Sends formatted alerts to a Telegram chat via Bot API.
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        rate_limit_per_minute: int = 20,
    ):
        self.bot_token = bot_token or settings.telegram_bot_token
        self.chat_id = chat_id or settings.telegram_chat_id
        self.rate_limit = rate_limit_per_minute
        self._http_client: Optional[httpx.AsyncClient] = None
        self._semaphore = asyncio.Semaphore(3)
        self._sent_count = 0
        self._error_count = 0
        self._last_reset = 0
        self._minute_count = 0

    @property
    def api_url(self) -> str:
        """Get Telegram Bot API URL."""
        return f"https://api.telegram.org/bot{self.bot_token}"

    async def start(self):
        """Start the Telegram alerter."""
        if not self.bot_token or not self.chat_id:
            logger.warning("Telegram bot not configured")
            return

        self._http_client = httpx.AsyncClient(timeout=30.0)
        logger.info("Telegram alerter started")

    async def stop(self):
        """Stop the Telegram alerter."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        logger.info("Telegram alerter stopped")

    async def send_alert(
        self,
        alert: Alert,
        cto_score: Optional[CTOScore] = None,
    ) -> bool:
        """
        Send an alert to Telegram.

        Returns True if successful.
        """
        if not self.bot_token or not self.chat_id or not self._http_client:
            return False

        # Rate limiting
        if not self._check_rate_limit():
            logger.warning("Telegram rate limit reached, skipping alert")
            return False

        # Format the message
        message = AlertFormatter.format_telegram(alert, cto_score)

        async with self._semaphore:
            try:
                response = await self._http_client.post(
                    f"{self.api_url}/sendMessage",
                    json={
                        "chat_id": self.chat_id,
                        "text": message,
                        "parse_mode": "Markdown",
                        "disable_web_page_preview": True,
                    }
                )

                data = response.json()

                if not data.get("ok"):
                    error_desc = data.get("description", "Unknown error")
                    logger.error(f"Telegram API error: {error_desc}")

                    # Handle rate limiting
                    if "retry after" in error_desc.lower():
                        retry_after = data.get("parameters", {}).get("retry_after", 5)
                        await asyncio.sleep(retry_after)
                        return await self.send_alert(alert, cto_score)

                    self._error_count += 1
                    return False

                self._sent_count += 1
                logger.info(f"Telegram alert sent for {alert.mint[:8]}")
                return True

            except Exception as e:
                self._error_count += 1
                logger.error(f"Telegram send error: {e}")
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
        """Send a test message to verify bot configuration."""
        if not self.bot_token or not self.chat_id or not self._http_client:
            return False

        try:
            response = await self._http_client.post(
                f"{self.api_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": "\U0001F916 Pocketwatcher connected and monitoring!",
                }
            )

            data = response.json()
            if data.get("ok"):
                logger.info("Telegram test message sent")
                return True
            else:
                logger.error(f"Telegram test failed: {data.get('description')}")
                return False

        except Exception as e:
            logger.error(f"Telegram test error: {e}")
            return False

    async def get_bot_info(self) -> Optional[dict]:
        """Get bot information to verify token."""
        if not self.bot_token or not self._http_client:
            return None

        try:
            response = await self._http_client.get(f"{self.api_url}/getMe")
            data = response.json()
            if data.get("ok"):
                return data.get("result")
        except Exception as e:
            logger.error(f"Failed to get bot info: {e}")

        return None

    def is_configured(self) -> bool:
        """Check if Telegram alerting is configured."""
        return bool(self.bot_token and self.chat_id)

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
