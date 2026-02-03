"""Metrics collection and monitoring."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from storage.redis_client import RedisClient

logger = logging.getLogger(__name__)


@dataclass
class Counter:
    """Simple counter metric."""
    name: str
    value: int = 0
    labels: Dict[str, str] = field(default_factory=dict)

    def inc(self, amount: int = 1):
        self.value += amount


@dataclass
class Gauge:
    """Simple gauge metric."""
    name: str
    value: float = 0.0
    labels: Dict[str, str] = field(default_factory=dict)

    def set(self, value: float):
        self.value = value


@dataclass
class Histogram:
    """Simple histogram metric with buckets."""
    name: str
    buckets: List[float] = field(default_factory=lambda: [0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0])
    counts: List[int] = None
    sum: float = 0.0
    count: int = 0
    labels: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if self.counts is None:
            self.counts = [0] * (len(self.buckets) + 1)

    def observe(self, value: float):
        self.sum += value
        self.count += 1
        for i, bucket in enumerate(self.buckets):
            if value <= bucket:
                self.counts[i] += 1
                return
        self.counts[-1] += 1  # +Inf bucket


class MetricsCollector:
    """
    Collects and exposes application metrics.

    Provides counters, gauges, and histograms for monitoring
    application health and performance.
    """

    def __init__(self):
        self._counters: Dict[str, Counter] = {}
        self._gauges: Dict[str, Gauge] = {}
        self._histograms: Dict[str, Histogram] = {}
        self._start_time = time.time()

    # === Counters ===

    def counter(self, name: str, labels: Optional[Dict[str, str]] = None) -> Counter:
        """Get or create a counter."""
        key = f"{name}:{labels}" if labels else name
        if key not in self._counters:
            self._counters[key] = Counter(name=name, labels=labels or {})
        return self._counters[key]

    def inc(self, name: str, amount: int = 1, labels: Optional[Dict[str, str]] = None):
        """Increment a counter."""
        self.counter(name, labels).inc(amount)

    # === Gauges ===

    def gauge(self, name: str, labels: Optional[Dict[str, str]] = None) -> Gauge:
        """Get or create a gauge."""
        key = f"{name}:{labels}" if labels else name
        if key not in self._gauges:
            self._gauges[key] = Gauge(name=name, labels=labels or {})
        return self._gauges[key]

    def set_gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """Set a gauge value."""
        self.gauge(name, labels).set(value)

    # === Histograms ===

    def histogram(
        self,
        name: str,
        buckets: Optional[List[float]] = None,
        labels: Optional[Dict[str, str]] = None
    ) -> Histogram:
        """Get or create a histogram."""
        key = f"{name}:{labels}" if labels else name
        if key not in self._histograms:
            self._histograms[key] = Histogram(
                name=name,
                buckets=buckets or [0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0],
                labels=labels or {},
            )
        return self._histograms[key]

    def observe(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None
    ):
        """Record an observation in a histogram."""
        self.histogram(name, labels=labels).observe(value)

    # === Convenience methods ===

    def record_tx_processed(self, venue: str = "unknown"):
        """Record a transaction was processed."""
        self.inc("tx_processed_total", labels={"venue": venue})

    def record_swap_detected(self, side: str, venue: str = "unknown"):
        """Record a swap was detected."""
        self.inc("swaps_detected_total", labels={"side": side, "venue": venue})

    def record_hot_token(self, trigger: str):
        """Record a HOT token trigger."""
        self.inc("hot_tokens_total", labels={"trigger": trigger})

    def record_alert_sent(self, channel: str):
        """Record an alert was sent."""
        self.inc("alerts_sent_total", labels={"channel": channel})

    def record_processing_time(self, seconds: float):
        """Record transaction processing time."""
        self.observe("tx_processing_seconds", seconds)

    def record_batch_time(self, seconds: float, batch_size: int):
        """Record batch processing time and per-tx average."""
        self.observe("batch_processing_seconds", seconds)
        if batch_size > 0:
            per_tx = seconds / batch_size
            self.observe("tx_processing_seconds", per_tx)
        self.inc("batches_processed_total")

    def set_stream_length(self, length: int):
        """Set current stream length."""
        self.set_gauge("stream_length", length)

    def set_processing_lag(self, seconds: float):
        """Set current processing lag."""
        self.set_gauge("processing_lag_seconds", seconds)

    def set_hot_token_count(self, count: int):
        """Set current HOT token count."""
        self.set_gauge("hot_tokens_current", count)

    # === Export ===

    def get_all_metrics(self) -> Dict[str, Any]:
        """Get all metrics as a dictionary."""
        return {
            "uptime_seconds": time.time() - self._start_time,
            "counters": {
                c.name: {"value": c.value, "labels": c.labels}
                for c in self._counters.values()
            },
            "gauges": {
                g.name: {"value": g.value, "labels": g.labels}
                for g in self._gauges.values()
            },
            "histograms": {
                h.name: {
                    "sum": h.sum,
                    "count": h.count,
                    "buckets": dict(zip(h.buckets + [float('inf')], h.counts)),
                    "labels": h.labels,
                }
                for h in self._histograms.values()
            },
        }

    def _sum_counters(self, name: str) -> int:
        """Sum counters with the same base name across all label sets."""
        return sum(counter.value for counter in self._counters.values() if counter.name == name)

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of key metrics."""
        tx_total = self._sum_counters("tx_processed_total")
        swap_total = self._sum_counters("swaps_detected_total")
        hot_total = self._sum_counters("hot_tokens_total")
        alert_total = self._sum_counters("alerts_sent_total")

        stream_gauge = self._gauges.get("stream_length", Gauge("stream_length"))
        lag_gauge = self._gauges.get("processing_lag_seconds", Gauge("processing_lag_seconds"))
        hot_gauge = self._gauges.get("hot_tokens_current", Gauge("hot_tokens_current"))

        uptime = time.time() - self._start_time

        return {
            "uptime_seconds": uptime,
            "uptime_human": self._format_duration(uptime),
            "transactions_processed": tx_total,
            "tx_per_second": tx_total / uptime if uptime > 0 else 0,
            "swaps_detected": swap_total,
            "hot_triggers": hot_total,
            "alerts_sent": alert_total,
            "stream_length": int(stream_gauge.value),
            "processing_lag_seconds": lag_gauge.value,
            "hot_tokens_current": int(hot_gauge.value),
        }

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format duration in human-readable format."""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            return f"{seconds / 60:.0f}m"
        elif seconds < 86400:
            return f"{seconds / 3600:.1f}h"
        else:
            return f"{seconds / 86400:.1f}d"


# Global metrics instance
metrics = MetricsCollector()


class HealthChecker:
    """
    System health checker.

    Runs periodic health checks and reports status.
    """

    def __init__(
        self,
        metrics_collector: MetricsCollector,
        redis_client: Optional[RedisClient] = None,
        check_interval: float = 10.0,
    ):
        self.metrics = metrics_collector
        self.redis = redis_client
        self.check_interval = check_interval
        self._is_healthy = True
        self._last_check = 0.0
        self._health_issues: List[str] = []

    async def check_health(self) -> Dict[str, Any]:
        """Run health checks and return status."""
        self._health_issues = []

        if self.redis:
            try:
                stream_length = await self.redis.get_stream_length()
                self.metrics.set_stream_length(stream_length)
            except Exception as e:
                logger.error(f"Health check stream length error: {e}")

        summary = self.metrics.get_summary()

        # Check processing lag
        if summary["processing_lag_seconds"] > 60:
            self._health_issues.append(
                f"High processing lag: {summary['processing_lag_seconds']:.0f}s"
            )

        # Check stream backlog
        if summary["stream_length"] > 50000:
            self._health_issues.append(
                f"Large stream backlog: {summary['stream_length']}"
            )

        # Check tx throughput (if running for > 1 minute)
        if summary["uptime_seconds"] > 60 and summary["tx_per_second"] < 1:
            self._health_issues.append(
                f"Low throughput: {summary['tx_per_second']:.1f} tx/s"
            )

        self._is_healthy = len(self._health_issues) == 0
        self._last_check = time.time()

        return {
            "healthy": self._is_healthy,
            "issues": self._health_issues,
            "summary": summary,
        }

    async def health_check_loop(self):
        """Run periodic health checks."""
        while True:
            try:
                await asyncio.sleep(self.check_interval)
                health = await self.check_health()

                if not health["healthy"]:
                    logger.warning(f"Health issues: {health['issues']}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check error: {e}")

    @property
    def is_healthy(self) -> bool:
        """Get current health status."""
        return self._is_healthy
