"""Closed contracts for offline Spark performance facts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from mcp_stdio.plugins.spark.inspection_models import (
    Count,
    InspectRequest,
    Sha256,
    SparkEventCoverage,
    SparkEventRef,
    SparkId,
    SparkSnapshot,
)
from mcp_stdio.plugins.spark.models import SparkModel, validate_attempt_id

MetricName = Literal[
    "duration_ms",
    "executor_run_time_ms",
    "jvm_gc_time_ms",
    "input_bytes",
    "shuffle_read_bytes",
    "shuffle_fetch_wait_ms",
]
Limit = Annotated[int, Field(ge=1, le=20)]


class MetricsSnapshotRequest(InspectRequest):
    expected_sha256: Sha256


class StageMetricsRequest(MetricsSnapshotRequest):
    stage_id: SparkId | None = None
    stage_attempt_id: SparkId | None = None
    limit: Limit = 20

    @model_validator(mode="after")
    def validate_stage_pair(self) -> StageMetricsRequest:
        if (self.stage_id is None) != (self.stage_attempt_id is None):
            raise ValueError("stage ID and attempt ID must be supplied together")
        return self


class TaskDistributionRequest(MetricsSnapshotRequest):
    stage_id: SparkId
    stage_attempt_id: SparkId
    order_by: MetricName = "duration_ms"
    limit: Limit = 20


class MetricTotal(SparkModel):
    total: Count | None
    valid_count: Count
    missing_count: Count


class MetricDistribution(SparkModel):
    valid_count: Count
    missing_count: Count
    min: Count | None
    p50: Count | None
    p95: Count | None
    max: Count | None


class TaskMetricValues(SparkModel):
    duration_ms: Count | None
    executor_run_time_ms: Count | None
    jvm_gc_time_ms: Count | None
    input_bytes: Count | None
    shuffle_read_bytes: Count | None
    shuffle_fetch_wait_ms: Count | None


class TaskMetricDistributions(SparkModel):
    duration_ms: MetricDistribution
    executor_run_time_ms: MetricDistribution
    jvm_gc_time_ms: MetricDistribution
    input_bytes: MetricDistribution
    shuffle_read_bytes: MetricDistribution
    shuffle_fetch_wait_ms: MetricDistribution


class SparkStageMetrics(SparkModel):
    stage_id: SparkId
    stage_attempt_id: SparkId
    submission_time_ms: SparkId | None
    completion_time_ms: SparkId | None
    duration_ms: Count | None
    submitted_ref: SparkEventRef | None
    completed_ref: SparkEventRef | None
    task_end_count: Count
    successful_task_end_count: Count
    non_success_task_end_count: Count
    unknown_reason_task_end_count: Count
    input_bytes: MetricTotal
    shuffle_read_bytes: MetricTotal


class SparkRankedTask(TaskMetricValues):
    task_id: SparkId | None
    executor_id: str | None
    ref: SparkEventRef

    _executor = field_validator("executor_id")(validate_attempt_id)


class SparkStageMetricsResult(SparkModel):
    snapshot: SparkSnapshot
    coverage: SparkEventCoverage
    matched_stage_attempt_count: Count
    unassigned_task_end_count: Count
    stages: Annotated[tuple[SparkStageMetrics, ...], Field(max_length=20)]
    stages_omitted: Count


class SparkTaskDistributionResult(SparkModel):
    snapshot: SparkSnapshot
    coverage: SparkEventCoverage
    stage_id: SparkId
    stage_attempt_id: SparkId
    task_end_count: Count
    successful_task_end_count: Count
    non_success_task_end_count: Count
    unknown_reason_task_end_count: Count
    distributions: TaskMetricDistributions
    order_by: MetricName
    ranked_task_count: Count
    top_tasks: Annotated[tuple[SparkRankedTask, ...], Field(max_length=20)]
    tasks_omitted: Count
