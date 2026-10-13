"""Full-file offline Spark metrics with only aggregate projections retained."""

from __future__ import annotations

import heapq
from array import array
from dataclasses import dataclass, field
from typing import cast

from mcp_stdio.plugins.spark.files import checkpoint
from mcp_stdio.plugins.spark.inspection_events import direct_ids
from mcp_stdio.plugins.spark.inspection_models import SparkEventIds, SparkEventRef
from mcp_stdio.plugins.spark.inspection_reader import VerifiedEventLogReader
from mcp_stdio.plugins.spark.metrics_events import (
    METRIC_NAMES,
    metric_distribution,
    metric_integer,
    task_metric_values,
    task_outcome,
)
from mcp_stdio.plugins.spark.metrics_models import (
    MetricTotal,
    SparkRankedTask,
    SparkStageMetrics,
    SparkStageMetricsResult,
    SparkTaskDistributionResult,
    StageMetricsRequest,
    TaskDistributionRequest,
    TaskMetricDistributions,
    TaskMetricValues,
)


@dataclass
class _Total:
    value: int = 0
    valid: int = 0

    def add(self, value: int | None) -> None:
        if value is not None:
            self.value += value
            self.valid += 1

    def result(self, successes: int) -> MetricTotal:
        return MetricTotal(total=self.value if self.valid else None,
                           valid_count=self.valid, missing_count=successes - self.valid)


@dataclass
class _Stage:
    submitted_line: int | None = None
    completed_line: int | None = None
    submitted_times: tuple[int | None, int | None] = (None, None)
    completed_times: tuple[int | None, int | None] = (None, None)
    successful: int = 0
    non_success: int = 0
    unknown: int = 0
    inputs: _Total = field(default_factory=_Total)
    shuffle: _Total = field(default_factory=_Total)

    @property
    def times(self) -> tuple[int | None, int | None]:
        return self.completed_times if self.completed_line is not None else self.submitted_times

    @property
    def duration(self) -> int | None:
        start, end = self.times
        return end - start if start is not None and end is not None and end >= start else None


def _stage_order(item: tuple[tuple[int, int], _Stage]) -> tuple[bool, int, int, int]:
    ids, stage = item
    duration = stage.duration
    return duration is None, -duration if duration is not None else 0, *ids


async def scan_stage_metrics(
    reader: VerifiedEventLogReader, request: StageMetricsRequest, *, deadline: float
) -> SparkStageMetricsResult:
    groups: dict[tuple[int, int], _Stage] = {}
    unassigned = 0

    def visit(line: int, event: dict[str, object]) -> None:
        nonlocal unassigned
        name = event["Event"]
        if name == "SparkListenerTaskEnd":
            source = event
        elif name in ("SparkListenerStageSubmitted", "SparkListenerStageCompleted"):
            info = event.get("Stage Info")
            source = cast(dict[str, object], info) if isinstance(info, dict) else {}
        else:
            return
        stage_id = metric_integer(source.get("Stage ID"))
        attempt_id = metric_integer(source.get("Stage Attempt ID"))
        if stage_id is None or attempt_id is None:
            unassigned += int(name == "SparkListenerTaskEnd")
            return
        if request.stage_id is not None and (stage_id, attempt_id) != (
            request.stage_id, request.stage_attempt_id
        ):
            return
        group = groups.setdefault((stage_id, attempt_id), _Stage())
        if name == "SparkListenerTaskEnd":
            outcome = task_outcome(event)
            if outcome == "success":
                group.successful += 1
                values = task_metric_values(event)
                group.inputs.add(values.input_bytes)
                group.shuffle.add(values.shuffle_read_bytes)
            elif outcome == "non_success":
                group.non_success += 1
            else:
                group.unknown += 1
        else:
            times = (metric_integer(source.get("Submission Time")),
                     metric_integer(source.get("Completion Time")))
            if name == "SparkListenerStageSubmitted":
                group.submitted_line, group.submitted_times = line, times
            else:
                group.completed_line, group.completed_times = line, times

    scan = await reader.read(request, visit, deadline=deadline)
    await checkpoint(deadline)
    selected = sorted(groups.items(), key=_stage_order)[:request.limit]
    await checkpoint(deadline)

    def ref(line: int | None) -> SparkEventRef | None:
        return SparkEventRef(sha256=scan.snapshot.sha256, line=line) if line is not None else None

    stages: list[SparkStageMetrics] = []
    for (stage_id, attempt_id), group in selected:
        await checkpoint(deadline)
        start, end = group.times
        stages.append(SparkStageMetrics(
            stage_id=stage_id, stage_attempt_id=attempt_id,
            submission_time_ms=start, completion_time_ms=end, duration_ms=group.duration,
            submitted_ref=ref(group.submitted_line), completed_ref=ref(group.completed_line),
            task_end_count=group.successful + group.non_success + group.unknown,
            successful_task_end_count=group.successful,
            non_success_task_end_count=group.non_success,
            unknown_reason_task_end_count=group.unknown,
            input_bytes=group.inputs.result(group.successful),
            shuffle_read_bytes=group.shuffle.result(group.successful),
        ))
    result = SparkStageMetricsResult(
        snapshot=scan.snapshot, coverage=scan.coverage,
        matched_stage_attempt_count=len(groups), unassigned_task_end_count=unassigned,
        stages=tuple(stages), stages_omitted=len(groups) - len(stages),
    )

    await checkpoint(deadline)
    return result


async def scan_task_distribution(
    reader: VerifiedEventLogReader, request: TaskDistributionRequest, *, deadline: float
) -> SparkTaskDistributionResult:
    samples = {name: array("Q") for name in METRIC_NAMES}
    candidates: list[tuple[int, int, TaskMetricValues, SparkEventIds]] = []
    successful = non_success = unknown = ranked = 0

    def visit(line: int, event: dict[str, object]) -> None:
        nonlocal successful, non_success, unknown, ranked
        if event["Event"] != "SparkListenerTaskEnd" or (
            metric_integer(event.get("Stage ID")),
            metric_integer(event.get("Stage Attempt ID")),
        ) != (request.stage_id, request.stage_attempt_id):
            return
        outcome = task_outcome(event)
        if outcome == "non_success":
            non_success += 1
            return
        if outcome == "unknown":
            unknown += 1
            return
        successful += 1
        values = task_metric_values(event)
        for name in METRIC_NAMES:
            value = getattr(values, name)
            if value is not None:
                samples[name].append(value)
        score = getattr(values, request.order_by)
        if score is not None:
            ranked += 1
            key = (score, -line)
            if len(candidates) < request.limit:
                heapq.heappush(candidates, (*key, values, direct_ids(event)))
            elif key > candidates[0][:2]:
                heapq.heapreplace(candidates, (*key, values, direct_ids(event)))

    scan = await reader.read(request, visit, deadline=deadline)
    await checkpoint(deadline)
    distributions = {}
    for name in METRIC_NAMES:
        await checkpoint(deadline)
        distributions[name] = metric_distribution(samples[name], successful)
        await checkpoint(deadline)
    await checkpoint(deadline)
    ordered = sorted(candidates, key=lambda item: (-item[0], -item[1]))
    await checkpoint(deadline)
    top_tasks: list[SparkRankedTask] = []
    for _, negative_line, values, ids in ordered:
        await checkpoint(deadline)
        top_tasks.append(
            SparkRankedTask(
                **values.model_dump(),
                task_id=ids.task_id,
                executor_id=ids.executor_id,
                ref=SparkEventRef(sha256=scan.snapshot.sha256, line=-negative_line),
            )
        )
    await checkpoint(deadline)
    result = SparkTaskDistributionResult(
        snapshot=scan.snapshot,
        coverage=scan.coverage,
        stage_id=request.stage_id,
        stage_attempt_id=request.stage_attempt_id,
        task_end_count=successful + non_success + unknown,
        successful_task_end_count=successful,
        non_success_task_end_count=non_success,
        unknown_reason_task_end_count=unknown,
        distributions=TaskMetricDistributions.model_validate(distributions),
        order_by=request.order_by,
        ranked_task_count=ranked,
        top_tasks=tuple(top_tasks),
        tasks_omitted=ranked - len(top_tasks),
    )
    await checkpoint(deadline)
    return result
