"""Pure fixed measurement extraction from one Spark TaskEnd event."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, cast

from mcp_stdio.plugins.spark.inspection_events import task_reason
from mcp_stdio.plugins.spark.metrics_models import MetricDistribution, MetricName, TaskMetricValues

METRIC_NAMES: tuple[MetricName, ...] = (
    "duration_ms", "executor_run_time_ms", "jvm_gc_time_ms",
    "input_bytes", "shuffle_read_bytes", "shuffle_fetch_wait_ms",
)


def metric_integer(value: object) -> int | None:
    """Validate a raw Spark numeric field without coercion."""
    return value if type(value) is int and 0 <= value <= 2**63 - 1 else None


def _object(value: object) -> dict[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def task_metric_values(event: dict[str, object]) -> TaskMetricValues:
    """Project six measurements independently; reason filtering belongs to the caller."""
    info = _object(event.get("Task Info"))
    metrics = _object(event.get("Task Metrics"))
    inputs = _object(metrics.get("Input Metrics"))
    shuffle = _object(metrics.get("Shuffle Read Metrics"))
    launch = metric_integer(info.get("Launch Time"))
    finish = metric_integer(info.get("Finish Time"))
    remote = metric_integer(shuffle.get("Remote Bytes Read"))
    local = metric_integer(shuffle.get("Local Bytes Read"))
    return TaskMetricValues(
        duration_ms=finish - launch
        if launch is not None and finish is not None and finish > 0 and finish >= launch
        else None,
        executor_run_time_ms=metric_integer(metrics.get("Executor Run Time")),
        jvm_gc_time_ms=metric_integer(metrics.get("JVM GC Time")),
        input_bytes=metric_integer(inputs.get("Bytes Read")),
        shuffle_read_bytes=remote + local if remote is not None and local is not None else None,
        shuffle_fetch_wait_ms=metric_integer(shuffle.get("Fetch Wait Time")),
    )


def task_outcome(event: dict[str, object]) -> Literal["success", "non_success", "unknown"]:
    reason, valid = task_reason(event)
    if not valid:
        return "unknown"
    return "success" if reason == "Success" else "non_success"


def metric_distribution(values: Sequence[int], successful_count: int) -> MetricDistribution:
    """Summarize already validated successful samples without modifying the input."""
    ordered = sorted(values)
    count = len(ordered)
    return MetricDistribution(
        valid_count=count,
        missing_count=successful_count - count,
        min=ordered[0] if count else None,
        p50=ordered[(50 * count + 99) // 100 - 1] if count else None,
        p95=ordered[(95 * count + 99) // 100 - 1] if count else None,
        max=ordered[-1] if count else None,
    )
