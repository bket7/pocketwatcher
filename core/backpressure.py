"""Backpressure and degradation management."""

import asyncio
import logging
import time
from enum import Enum
from typing import Optional

from config.settings import settings
from storage.redis_client import RedisClient

logger = logging.getLogger(__name__)


class DegradationMode(str, Enum):
    """System degradation modes."""
    NORMAL = "normal"      # Full parsing + SwapEventFull
    DEGRADED = "degraded"  # MintTouchedEvent + TxDeltaRecord only
    CRITICAL = "critical"  # Signature + mints only, pause enrichment


class BackpressureManager:
    """
    Manages system backpressure and degradation.

    Monitors:
    - Processing lag (time between tx block_time and processing)
    - Redis stream length
    - Resource utilization

    Triggers degradation when thresholds exceeded.
    """

    def __init__(
        self,
        redis_client: RedisClient,
        degraded_lag_seconds: Optional[int] = None,
        critical_lag_seconds: Optional[int] = None,
        degraded_stream_len: Optional[int] = None,
        critical_stream_len: Optional[int] = None,
    ):
        self.redis = redis_client
        self.degraded_lag = degraded_lag_seconds or settings.degraded_lag_seconds
        self.critical_lag = critical_lag_seconds or settings.critical_lag_seconds
        self.degraded_stream_len = degraded_stream_len or settings.degraded_stream_len
        self.critical_stream_len = critical_stream_len or settings.critical_stream_len

        self._current_mode = DegradationMode.NORMAL
        self._last_check = 0
        self._check_interval = 1.0  # Check every second
        self._mode_changes = 0

        # Tracking
        self._last_block_time = 0
        self._processing_lag = 0.0
        self._stream_length = 0

    @property
    def mode(self) -> DegradationMode:
        """Get current degradation mode."""
        return self._current_mode

    def is_normal(self) -> bool:
        """Check if in normal mode."""
        return self._current_mode == DegradationMode.NORMAL

    def is_degraded(self) -> bool:
        """Check if in degraded or critical mode."""
        return self._current_mode in (DegradationMode.DEGRADED, DegradationMode.CRITICAL)

    def is_critical(self) -> bool:
        """Check if in critical mode."""
        return self._current_mode == DegradationMode.CRITICAL

    async def update(self, block_time: Optional[int] = None) -> DegradationMode:
        """
        Update backpressure state.

        Call this periodically or on each processed transaction.

        Args:
            block_time: Block time of last processed transaction

        Returns:
            Current degradation mode
        """
        now = time.time()

        # Don't check too frequently
        if now - self._last_check < self._check_interval:
            return self._current_mode

        self._last_check = now

        # Calculate processing lag
        if block_time:
            self._last_block_time = block_time
            self._processing_lag = now - block_time

        # Get stream length
        try:
            self._stream_length = await self.redis.get_stream_length()
        except Exception as e:
            logger.error(f"Failed to get stream length: {e}")

        # Determine mode
        new_mode = self._calculate_mode()

        if new_mode != self._current_mode:
            self._mode_changes += 1
            logger.warning(
                f"Degradation mode changed: {self._current_mode} -> {new_mode} "
                f"(lag={self._processing_lag:.1f}s, stream={self._stream_length})"
            )
            self._current_mode = new_mode

        return self._current_mode

    def _calculate_mode(self) -> DegradationMode:
        """Calculate degradation mode from current metrics."""
        # Critical thresholds
        if self._processing_lag > self.critical_lag:
            return DegradationMode.CRITICAL
        if self._stream_length > self.critical_stream_len:
            return DegradationMode.CRITICAL

        # Degraded thresholds
        if self._processing_lag > self.degraded_lag:
            return DegradationMode.DEGRADED
        if self._stream_length > self.degraded_stream_len:
            return DegradationMode.DEGRADED

        return DegradationMode.NORMAL

    def should_store_swap_event(self) -> bool:
        """Check if we should store full swap events."""
        return self._current_mode == DegradationMode.NORMAL

    def should_enrich(self) -> bool:
        """Check if we should run enrichment."""
        return self._current_mode != DegradationMode.CRITICAL

    def should_parse_full(self) -> bool:
        """Check if we should do full parsing."""
        return self._current_mode == DegradationMode.NORMAL

    def get_stats(self) -> dict:
        """Get backpressure statistics."""
        return {
            "mode": self._current_mode.value,
            "processing_lag_seconds": self._processing_lag,
            "stream_length": self._stream_length,
            "mode_changes": self._mode_changes,
            "thresholds": {
                "degraded_lag": self.degraded_lag,
                "critical_lag": self.critical_lag,
                "degraded_stream_len": self.degraded_stream_len,
                "critical_stream_len": self.critical_stream_len,
            },
        }


class CircuitBreaker:
    """
    Circuit breaker for external service calls.

    Prevents cascading failures by stopping calls
    to failing services.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self._failures = 0
        self._last_failure = 0.0
        self._is_open = False

    def is_open(self) -> bool:
        """Check if circuit is open (blocking calls)."""
        if not self._is_open:
            return False

        # Check if recovery timeout has passed
        if time.time() - self._last_failure > self.recovery_timeout:
            self._is_open = False
            self._failures = 0
            logger.info("Circuit breaker reset")
            return False

        return True

    def record_success(self):
        """Record a successful call."""
        self._failures = 0

    def record_failure(self):
        """Record a failed call."""
        self._failures += 1
        self._last_failure = time.time()

        if self._failures >= self.failure_threshold:
            self._is_open = True
            logger.warning(
                f"Circuit breaker opened after {self._failures} failures"
            )

    async def call(self, func, *args, **kwargs):
        """
        Execute function with circuit breaker protection.

        Raises RuntimeError if circuit is open.
        """
        if self.is_open():
            raise RuntimeError("Circuit breaker is open")

        try:
            result = await func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            raise

    def get_stats(self) -> dict:
        """Get circuit breaker statistics."""
        return {
            "is_open": self._is_open,
            "failures": self._failures,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }
