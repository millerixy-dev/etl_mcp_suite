"""Bounded full-file overview of verified local Spark event evidence."""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import cast

from mcp_stdio.plugins.spark.config import SparkSettings
from mcp_stdio.plugins.spark.files import credential_values
from mcp_stdio.plugins.spark.inspection_events import direct_ids, event_details, task_reason
from mcp_stdio.plugins.spark.inspection_models import (
    EventTypeCount,
    InspectRequest,
    SparkEventEvidence,
    SparkEventLogInspectionResult,
    SparkEventRef,
    SparkFailureSignals,
    TaskReasonCount,
)
from mcp_stdio.plugins.spark.inspection_reader import VerifiedEventLogReader


class SparkInspectionAdapter:
    def __init__(self, settings: SparkSettings, secret_values: tuple[str, ...] = ()) -> None:
        self._reader = VerifiedEventLogReader(settings, secret_values)
        self._secrets = credential_values(secret_values)
        self._active: set[asyncio.Task[SparkEventLogInspectionResult]] = set()
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

    async def close(self) -> None:
        self._closed = True
        active = tuple(self._active)
        for worker in active:
            worker.cancel()
        await asyncio.gather(*active, return_exceptions=True)

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
            task_end_reasons=tuple(
                TaskReasonCount(reason=name, count=count)
                for name, count in sorted(reasons.items(), key=lambda item: (-item[1], item[0]))[
                    :32
                ]
            ),
            reasons_omitted=max(0, len(reasons) - 32),
            evidence=tuple(evidence),
            evidence_omitted=(failure_count or ending_count) - len(evidence),
            coverage=scan.coverage,
        )
