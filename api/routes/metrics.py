"""Prometheus /metrics endpoint."""

import logging

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from core.monitoring import metrics

logger = logging.getLogger(__name__)

router = APIRouter(tags=["metrics"])


def generate_prometheus_output() -> str:
    """
    Generate Prometheus exposition format from MetricsCollector.

    Format spec: https://prometheus.io/docs/instrumenting/exposition_formats/
    """
    lines = []

    # Get all metrics
    all_metrics = metrics.get_all_metrics()

    # Uptime
    lines.append("# HELP pocketwatcher_uptime_seconds Time since service start")
    lines.append("# TYPE pocketwatcher_uptime_seconds gauge")
    lines.append(f'pocketwatcher_uptime_seconds {all_metrics["uptime_seconds"]:.3f}')
    lines.append("")

    # Counters
    counters_by_name = {}
    for counter in metrics._counters.values():
        if counter.name not in counters_by_name:
            counters_by_name[counter.name] = []
        counters_by_name[counter.name].append(counter)

    for name, counter_list in counters_by_name.items():
        prom_name = f"pocketwatcher_{name}"
        lines.append(f"# HELP {prom_name} Counter metric")
        lines.append(f"# TYPE {prom_name} counter")
        for counter in counter_list:
            labels = _format_labels(counter.labels)
            lines.append(f"{prom_name}{labels} {counter.value}")
        lines.append("")

    # Gauges
    gauges_by_name = {}
    for gauge in metrics._gauges.values():
        if gauge.name not in gauges_by_name:
            gauges_by_name[gauge.name] = []
        gauges_by_name[gauge.name].append(gauge)

    for name, gauge_list in gauges_by_name.items():
        prom_name = f"pocketwatcher_{name}"
        lines.append(f"# HELP {prom_name} Gauge metric")
        lines.append(f"# TYPE {prom_name} gauge")
        for gauge in gauge_list:
            labels = _format_labels(gauge.labels)
            lines.append(f"{prom_name}{labels} {gauge.value}")
        lines.append("")

    # Histograms
    histograms_by_name = {}
    for histogram in metrics._histograms.values():
        if histogram.name not in histograms_by_name:
            histograms_by_name[histogram.name] = []
        histograms_by_name[histogram.name].append(histogram)

    for name, histogram_list in histograms_by_name.items():
        prom_name = f"pocketwatcher_{name}"
        lines.append(f"# HELP {prom_name} Histogram metric")
        lines.append(f"# TYPE {prom_name} histogram")
        for histogram in histogram_list:
            base_labels = histogram.labels
            cumulative = 0
            # Bucket lines
            for i, bucket in enumerate(histogram.buckets):
                cumulative += histogram.counts[i]
                labels = _format_labels({**base_labels, "le": str(bucket)})
                lines.append(f"{prom_name}_bucket{labels} {cumulative}")
            # +Inf bucket
            cumulative += histogram.counts[-1]
            labels = _format_labels({**base_labels, "le": "+Inf"})
            lines.append(f"{prom_name}_bucket{labels} {cumulative}")
            # Sum and count
            sum_labels = _format_labels(base_labels)
            lines.append(f"{prom_name}_sum{sum_labels} {histogram.sum}")
            lines.append(f"{prom_name}_count{sum_labels} {histogram.count}")
        lines.append("")

    return "\n".join(lines)


def _format_labels(labels: dict) -> str:
    """Format labels as Prometheus label string."""
    if not labels:
        return ""
    label_parts = [f'{k}="{v}"' for k, v in sorted(labels.items())]
    return "{" + ",".join(label_parts) + "}"


@router.get("/metrics", response_class=PlainTextResponse)
async def get_metrics():
    """
    Prometheus metrics endpoint.

    Returns metrics in Prometheus exposition format for scraping.
    """
    return generate_prometheus_output()
