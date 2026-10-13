"""Bounded full-file overview of verified local Spark event evidence."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable
from typing import cast

from mcp_stdio.plugins.spark.config import SparkSettings
from mcp_stdio.plugins.spark.files import credential_values
from mcp_stdio.plugins.spark.inspection_events import direct_ids, event_details, task_reason
from mcp_stdio.plugins.spark.inspection_models import (
    EventTypeCount,
    InspectRequest,
    QueryRequest,
    SparkEventEvidence,
    SparkEventLogInspectionResult,
    SparkEventQueryResult,
    SparkEventRef,
    SparkFailureSignals,
    TaskReasonCount,
)
from mcp_stdio.plugins.spark.inspection_reader import VerifiedEventLogReader
from mcp_stdio.plugins.spark.metrics import scan_stage_metrics
from mcp_stdio.plugins.spark.metrics_models import SparkStageMetricsResult, StageMetricsRequest


def _reason_counts(reasons: Counter[str]) -> tuple[TaskReasonCount, ...]:
    return tuple(
        TaskReasonCount(reason=name, count=count)
        for name, count in sorted(reasons.items(), key=lambda item: (-item[1], item[0]))[:32]
    )


class SparkInspectionAdapter:
    def __init__(self, settings: SparkSettings, secret_values: tuple[str, ...] = ()) -> None:
        self._reader = VerifiedEventLogReader(settings, secret_values)
        self._secrets = credential_values(secret_values)
        self._active: set[
            asyncio.Task[SparkEventLogInspectionResult]
            | asyncio.Task[SparkEventQueryResult]
            | asyncio.Task[SparkStageMetricsResult]
        ] = set()
        self._closed = False

    async def inspect(
        self, request: InspectRequest, *, deadline: float
    ) -> SparkEventLogInspectionResult:
        if self._closed:
            raise asyncio.CancelledError
        worker = asyncio.create_task(self._inspect(request, deadline=deadline))
        self._active.add(worker)
        try:
            return await worker
        finally:
            self._active.discard(worker)

    async def query(self, request: QueryRequest, *, deadline: float) -> SparkEventQueryResult:
        if self._closed:
            raise asyncio.CancelledError
        worker = asyncio.create_task(self._query(request, deadline=deadline))
        self._active.add(worker)
        try:
            return await worker
        finally:
            self._active.discard(worker)

    async def stage_metrics(
        self, request: StageMetricsRequest, *, deadline: float
    ) -> SparkStageMetricsResult:
        if self._closed:
            raise asyncio.CancelledError
        worker = asyncio.create_task(scan_stage_metrics(self._reader, request, deadline=deadline))
        self._active.add(worker)
        try:
            return await worker
        finally:
            self._active.discard(worker)

    async def _query(self, request: QueryRequest, *, deadline: float) -> SparkEventQueryResult:
        reasons: Counter[str] = Counter()
        entries: list[SparkEventEvidence] = []
        matched = eligible = 0
        id_filters = {
            field: value
            for field in (
                "execution_id",
                "job_id",
                "stage_id",
                "stage_attempt_id",
                "task_id",
                "executor_id",
            )
            if (value := getattr(request, field)) is not None
        }

        def visit(line: int, event: dict[str, object]) -> None:
            nonlocal matched, eligible
            name = str(event["Event"])
            if request.event_types is not None and name not in request.event_types:
                return
            if request.lines is not None and line not in request.lines:
                return
            ids = direct_ids(event)
            if any(getattr(ids, field) != value for field, value in id_filters.items()):
                return
            reason = task_reason(event)[0] if name == "SparkListenerTaskEnd" else None
            if request.task_end_reason is not None and reason != request.task_end_reason:
                return
            matched += 1
            if reason is not None:
                reasons[reason] += 1
            if line <= request.after_line:
                return
            eligible += 1
            if len(entries) >= request.limit:
                return
            details, truncated = event_details(event, self._secrets, request.max_detail_chars)
            entries.append(
                SparkEventEvidence(
                    ref=SparkEventRef(sha256="0" * 64, line=line),
                    event_type=name,
                    ids=ids,
                    details=details,
                    details_truncated=truncated,
                )
            )

        scan = await self._reader.read(request, visit, deadline=deadline)
        events = tuple(
            entry.model_copy(
                update={"ref": SparkEventRef(sha256=scan.snapshot.sha256, line=entry.ref.line)}
            )
            for entry in entries
        )
        return SparkEventQueryResult(
            snapshot=scan.snapshot,
            matched_count=matched,
            task_end_count=sum(reasons.values()),
            task_end_reasons=_reason_counts(reasons),
            reasons_omitted=max(0, len(reasons) - 32),
            events=events,
            returned_count=len(events),
            next_after_line=events[-1].ref.line if eligible > len(events) and events else None,
            coverage=scan.coverage,
        )

    async def close(self) -> None:
        self._closed = True
        active = tuple(self._active)
        for worker in active:
            worker.cancel()
        await asyncio.gather(
            *(cast(Awaitable[object], worker) for worker in active), return_exceptions=True
        )

    async def _inspect(
        self, request: InspectRequest, *, deadline: float
    ) -> SparkEventLogInspectionResult:
        types: Counter[str] = Counter()
        reasons: Counter[str] = Counter()
        signals = [0, 0, 0, 0]
        failures: list[tuple[int, int, SparkEventEvidence]] = []
        endings: list[tuple[int, int, SparkEventEvidence]] = []
        failure_count = ending_count = 0

        def evidence_entry(line: int, event: dict[str, object]) -> SparkEventEvidence:
            details, truncated = event_details(event, self._secrets)
            # The provisional ref stays internal; only verified EOF binds the real digest.
            return SparkEventEvidence(
                ref=SparkEventRef(sha256="0" * 64, line=line),
                event_type=str(event["Event"]),
                ids=direct_ids(event),
                details=details,
                details_truncated=truncated,
            )

        def visit(line: int, event: dict[str, object]) -> None:
            nonlocal failure_count, ending_count
            name = str(event["Event"])
            types[name] += 1
            priority: int | None = None
            if name == "SparkListenerJobEnd":
                result = event.get("Job Result")
                if (
                    isinstance(result, dict)
                    and cast(dict[str, object], result).get("Result") == "JobFailed"
                ):
                    priority = 0
            elif name == "SparkListenerStageCompleted":
                info = event.get("Stage Info")
                reason = (
                    cast(dict[str, object], info).get("Failure Reason")
                    if isinstance(info, dict)
                    else None
                )
                if isinstance(reason, str) and reason:
                    priority = 1
            elif name == "SparkListenerTaskEnd":
                reason, valid = task_reason(event)
                reasons[reason] += 1
                if valid and reason != "Success":
                    priority = 2
            elif name == "SparkListenerExecutorRemoved":
                priority = 3
            if priority is not None:
                signals[priority] += 1
                failure_count += 1
                if len(failures) < 20 or (priority, line) < failures[-1][:2]:
                    failures.append((priority, line, evidence_entry(line, event)))
                    failures.sort(key=lambda item: (item[0], item[1]))
                    if len(failures) > 20:
                        failures.pop()
            elif name in (
                "SparkListenerJobEnd",
                "org.apache.spark.sql.execution.ui.SparkListenerSQLExecutionEnd",
                "SparkListenerApplicationEnd",
            ):
                ending_count += 1
                if len(endings) < 20:
                    endings.append((0, line, evidence_entry(line, event)))

        scan = await self._reader.read(request, visit, deadline=deadline)
        selected = failures if failure_count else endings
        evidence = tuple(
            entry.model_copy(update={"ref": SparkEventRef(sha256=scan.snapshot.sha256, line=line)})
            for _, line, entry in selected
        )
        return SparkEventLogInspectionResult(
            snapshot=scan.snapshot,
            spark_version=scan.spark_version,
            event_count=scan.event_count,
            event_types=tuple(
                EventTypeCount(event_type=name, count=count)
                for name, count in sorted(types.items(), key=lambda item: (-item[1], item[0]))[:32]
            ),
            event_types_omitted=max(0, len(types) - 32),
            signals=SparkFailureSignals(
                job_failed_events=signals[0],
                stage_failure_events=signals[1],
                task_non_success_events=signals[2],
                executor_removed_events=signals[3],
            ),
            task_end_count=sum(reasons.values()),
            task_end_reasons=_reason_counts(reasons),
            reasons_omitted=max(0, len(reasons) - 32),
            evidence=tuple(evidence),
            evidence_omitted=(failure_count or ending_count) - len(evidence),
            coverage=scan.coverage,
        )
