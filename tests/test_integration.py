"""Integration tests for retry, shutdown, and pending message claiming."""

import asyncio
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from alerting.discord import DiscordAlerter
from stream.consumer import StreamConsumer, PENDING_CLAIM_MIN_IDLE_MS
from models.profiles import Alert
from enrichment.scoring import CTOScore


class TestDiscordRetry:
    """Tests for Discord retry logic with exponential backoff."""

    @pytest.fixture
    def mock_alert(self):
        return Alert(
            mint="TokenMint123456789",
            token_symbol="TEST",
            trigger_name="test",
            trigger_reason="test",
            buy_count_5m=20,
            unique_buyers_5m=5,
            volume_sol_5m=10.0,
            buy_sell_ratio_5m=5.0,
            top_buyers=[],
            cluster_summary="",
            enrichment_degraded=False,
            created_at=datetime.utcnow(),
        )

    @pytest.mark.asyncio
    async def test_retry_on_network_error(self, mock_alert):
        """Test that network errors trigger retries."""
        alerter = DiscordAlerter(webhook_url="https://discord.com/api/webhooks/test")

        # Mock HTTP client that fails first two times, succeeds third
        call_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.ConnectError("Connection failed")
            response = MagicMock()
            response.status_code = 204
            response.raise_for_status = MagicMock()
            return response

        alerter._http_client = MagicMock()
        alerter._http_client.post = mock_post

        # Should succeed after retries
        with patch('asyncio.sleep', new_callable=AsyncMock):
            result = await alerter.send_alert(mock_alert)

        assert result is True
        assert call_count == 3
        assert alerter._sent_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_server_error(self, mock_alert):
        """Test that 5xx errors trigger retries."""
        alerter = DiscordAlerter(webhook_url="https://discord.com/api/webhooks/test")

        # Mock HTTP client that returns 500 first two times
        call_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            response = MagicMock()
            if call_count < 3:
                response.status_code = 500
            else:
                response.status_code = 204
                response.raise_for_status = MagicMock()
            return response

        alerter._http_client = MagicMock()
        alerter._http_client.post = mock_post

        with patch('asyncio.sleep', new_callable=AsyncMock):
            result = await alerter.send_alert(mock_alert)

        assert result is True
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_client_error(self, mock_alert):
        """Test that 4xx errors (except 429) don't retry."""
        alerter = DiscordAlerter(webhook_url="https://discord.com/api/webhooks/test")

        async def mock_post(*args, **kwargs):
            response = MagicMock()
            response.status_code = 400
            response.raise_for_status = MagicMock(
                side_effect=httpx.HTTPStatusError("Bad request", request=MagicMock(), response=response)
            )
            return response

        alerter._http_client = MagicMock()
        alerter._http_client.post = mock_post

        result = await alerter.send_alert(mock_alert)

        assert result is False
        assert alerter._error_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_rate_limit(self, mock_alert):
        """Test that 429 errors trigger wait and retry."""
        alerter = DiscordAlerter(webhook_url="https://discord.com/api/webhooks/test")

        call_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            response = MagicMock()
            if call_count == 1:
                response.status_code = 429
                response.json = MagicMock(return_value={"retry_after": 1})
            else:
                response.status_code = 204
                response.raise_for_status = MagicMock()
            return response

        alerter._http_client = MagicMock()
        alerter._http_client.post = mock_post

        with patch('asyncio.sleep', new_callable=AsyncMock):
            result = await alerter.send_alert(mock_alert)

        assert result is True
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(self, mock_alert):
        """Test that failures after max retries return False."""
        alerter = DiscordAlerter(webhook_url="https://discord.com/api/webhooks/test")

        async def mock_post(*args, **kwargs):
            raise httpx.ConnectError("Connection failed")

        alerter._http_client = MagicMock()
        alerter._http_client.post = mock_post

        with patch('asyncio.sleep', new_callable=AsyncMock):
            result = await alerter.send_alert(mock_alert)

        assert result is False
        assert alerter._error_count == 1


class TestPendingMessageClaiming:
    """Tests for pending message claiming on restart."""

    @pytest.mark.asyncio
    async def test_claim_pending_messages(self):
        """Test that pending messages are claimed and processed."""
        mock_redis = MagicMock()

        # Mock pending messages
        pending_messages = [
            {"message_id": "1-0", "time_since_delivered": 60000},  # 60s idle
            {"message_id": "2-0", "time_since_delivered": 45000},  # 45s idle
            {"message_id": "3-0", "time_since_delivered": 10000},  # 10s idle (below threshold)
        ]

        # Mock claimed messages
        claimed_messages = [
            ("1-0", {b"data": b"message1"}),
            ("2-0", {b"data": b"message2"}),
        ]

        mock_redis.redis = MagicMock()
        mock_redis.redis.xpending_range = AsyncMock(return_value=pending_messages)
        mock_redis.redis.xclaim = AsyncMock(return_value=claimed_messages)
        mock_redis.ack_messages = AsyncMock()

        consumer = StreamConsumer(mock_redis, consumer_name="test-1")

        processed_messages = []

        async def on_message(msg_id, data):
            processed_messages.append((msg_id, data))

        processed_count = await consumer._claim_pending_messages(on_message)

        # Should only process 2 messages (those idle > threshold)
        assert processed_count == 2
        assert len(processed_messages) == 2
        mock_redis.ack_messages.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_pending_messages(self):
        """Test handling when no pending messages exist."""
        mock_redis = MagicMock()
        mock_redis.redis = MagicMock()
        mock_redis.redis.xpending_range = AsyncMock(return_value=[])

        consumer = StreamConsumer(mock_redis, consumer_name="test-1")

        async def on_message(msg_id, data):
            pass

        processed_count = await consumer._claim_pending_messages(on_message)

        assert processed_count == 0

    @pytest.mark.asyncio
    async def test_pending_claim_on_start(self):
        """Test that pending messages are claimed when consumer starts."""
        mock_redis = MagicMock()
        mock_redis.redis = MagicMock()
        mock_redis.redis.xpending_range = AsyncMock(return_value=[])
        mock_redis.read_from_stream = AsyncMock(return_value=[])

        consumer = StreamConsumer(mock_redis, consumer_name="test-1")

        claim_called = False
        original_claim = consumer._claim_pending_messages

        async def mock_claim(*args, **kwargs):
            nonlocal claim_called
            claim_called = True
            return 0

        consumer._claim_pending_messages = mock_claim

        # Start and immediately stop
        async def run_briefly():
            task = asyncio.create_task(
                consumer.start(on_message=AsyncMock())
            )
            await asyncio.sleep(0.1)
            consumer.stop()
            await task

        await run_briefly()

        assert claim_called is True


class TestGracefulShutdown:
    """Tests for graceful shutdown behavior."""

    @pytest.mark.asyncio
    async def test_consumer_stops_gracefully(self):
        """Test that consumer stops cleanly on shutdown signal."""
        mock_redis = MagicMock()
        mock_redis.redis = MagicMock()
        mock_redis.redis.xpending_range = AsyncMock(return_value=[])
        mock_redis.read_from_stream = AsyncMock(return_value=[])
        mock_redis.ack_messages = AsyncMock()

        consumer = StreamConsumer(mock_redis, consumer_name="test-1")

        messages_processed = 0

        async def on_message(msg_id, data):
            nonlocal messages_processed
            messages_processed += 1
            await asyncio.sleep(0.01)

        # Start consumer in background
        task = asyncio.create_task(
            consumer.start(on_message=on_message)
        )

        # Wait briefly then signal stop
        await asyncio.sleep(0.1)
        consumer.stop()

        # Should complete without hanging
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except asyncio.TimeoutError:
            pytest.fail("Consumer did not stop within timeout")

        assert consumer._running is False

    @pytest.mark.asyncio
    async def test_multi_consumer_stops_all(self):
        """Test that multi-consumer stops all workers."""
        from stream.consumer import MultiConsumer

        mock_redis = MagicMock()
        mock_redis.redis = MagicMock()
        mock_redis.redis.xpending_range = AsyncMock(return_value=[])
        mock_redis.read_from_stream = AsyncMock(return_value=[])
        mock_redis.ack_messages = AsyncMock()

        multi = MultiConsumer(mock_redis, num_consumers=3)

        # Start
        await multi.start(on_message=AsyncMock())

        assert len(multi._consumers) == 3
        assert all(c._running for c in multi._consumers)

        # Stop
        await asyncio.wait_for(multi.stop(), timeout=5.0)

        assert len(multi._consumers) == 0

    @pytest.mark.asyncio
    async def test_discord_alerter_cleanup(self):
        """Test that Discord alerter cleans up HTTP client on stop."""
        alerter = DiscordAlerter(webhook_url="https://discord.com/api/webhooks/test")

        alerter._http_client = MagicMock()
        alerter._http_client.aclose = AsyncMock()

        await alerter.stop()

        alerter._http_client.aclose.assert_called_once()
        assert alerter._http_client is None


class TestRateLimiting:
    """Tests for Discord rate limiting."""

    def test_rate_limit_check(self):
        """Test rate limit checking."""
        alerter = DiscordAlerter(
            webhook_url="https://discord.com/api/webhooks/test",
            rate_limit_per_minute=5,
        )

        # Should allow first 5 requests
        for _ in range(5):
            assert alerter._check_rate_limit() is True

        # 6th should be blocked
        assert alerter._check_rate_limit() is False

    def test_rate_limit_resets(self):
        """Test that rate limit resets after minute changes."""
        alerter = DiscordAlerter(
            webhook_url="https://discord.com/api/webhooks/test",
            rate_limit_per_minute=2,
        )

        # Use up limit
        alerter._check_rate_limit()
        alerter._check_rate_limit()
        assert alerter._check_rate_limit() is False

        # Simulate minute change
        alerter._last_reset = 0

        # Should allow again
        assert alerter._check_rate_limit() is True
