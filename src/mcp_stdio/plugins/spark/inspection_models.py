"""Closed contracts for read-only local Spark evidence inspection."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, field_validator, model_validator

from mcp_stdio.plugins.spark.models import (
    SparkModel,
    validate_application_id,
    validate_attempt_id,
    validate_local_path,
)

SparkId = Annotated[int, Field(ge=0, le=2**63 - 1)]
PhysicalLine = Annotated[int, Field(ge=1, le=2**63 - 1)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Count = Annotated[int, Field(ge=0)]
EventType = Annotated[str, Field(min_length=1, max_length=512)]
TaskReason = Annotated[str, Field(min_length=1, max_length=128)]


def validate_plain_text(value: str) -> str:
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("invalid control character")
    return value


class InspectRequest(SparkModel):
    manifest_path: str
    attempt_id: str | None

    _path = field_validator("manifest_path")(validate_local_path)
    _attempt = field_validator("attempt_id")(validate_attempt_id)


class QueryRequest(InspectRequest):
    expected_sha256: Sha256
    event_types: Annotated[list[EventType], Field(min_length=1, max_length=16)] | None = None
    execution_id: SparkId | None = None
    job_id: SparkId | None = None
    stage_id: SparkId | None = None
    stage_attempt_id: SparkId | None = None
    task_id: SparkId | None = None
    executor_id: str | None = None
    task_end_reason: TaskReason | None = None
    lines: Annotated[list[PhysicalLine], Field(min_length=1, max_length=20)] | None = None
    after_line: SparkId = 0
    limit: Annotated[int, Field(ge=1, le=20)] = 20
    max_detail_chars: Annotated[int, Field(ge=1, le=32768)] = 2048

    _executor = field_validator("executor_id")(validate_attempt_id)

    @field_validator("event_types")
    @classmethod
    def validate_event_types(cls, values: list[str] | None) -> list[str] | None:
        if values is not None:
            for value in values:
                validate_plain_text(value)
        return values

    @field_validator("task_end_reason")
    @classmethod
    def validate_reason(cls, value: str | None) -> str | None:
        return validate_plain_text(value) if value is not None else None

    @model_validator(mode="after")
    def validate_selection(self) -> QueryRequest:
        if self.stage_attempt_id is not None and self.stage_id is None:
            raise ValueError("stage attempt requires stage ID")
        if self.lines is not None and len(set(self.lines)) != len(self.lines):
            raise ValueError("duplicate physical line")
        if self.max_detail_chars > 2048 and (
            self.lines is None or len(self.lines) != 1 or self.limit != 1
        ):
            raise ValueError("expanded detail requires a single line and limit one")
        return self


class SparkSnapshot(SparkModel):
    application_id: str
    attempt_id: str | None
    sha256: Sha256

    _application = field_validator("application_id")(validate_application_id)
    _attempt = field_validator("attempt_id")(validate_attempt_id)


class SparkEventRef(SparkModel):
    sha256: Sha256
    line: PhysicalLine


class SparkEventIds(SparkModel):
    execution_id: SparkId | None
    job_id: SparkId | None
    stage_id: SparkId | None
    stage_attempt_id: SparkId | None
    task_id: SparkId | None
    executor_id: str | None

    _executor = field_validator("executor_id")(validate_attempt_id)


class SparkEventEvidence(SparkModel):
    ref: SparkEventRef
    event_type: EventType
    ids: SparkEventIds
    details: Annotated[str, Field(max_length=32768)]
    details_truncated: bool

    _event_type = field_validator("event_type")(validate_plain_text)


class SparkEventCoverage(SparkModel):
    application_start_seen: bool
    application_end_seen: bool


class EventTypeCount(SparkModel):
    event_type: EventType
    count: Count

    _event_type = field_validator("event_type")(validate_plain_text)


class TaskReasonCount(SparkModel):
    reason: TaskReason
    count: Count

    _reason = field_validator("reason")(validate_plain_text)


class SparkFailureSignals(SparkModel):
    job_failed_events: Count
    stage_failure_events: Count
    task_non_success_events: Count
    executor_removed_events: Count


class SparkEventLogInspectionResult(SparkModel):
    snapshot: SparkSnapshot
    spark_version: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,128}$")] | None
    event_count: Count
    event_types: Annotated[tuple[EventTypeCount, ...], Field(max_length=32)]
    event_types_omitted: Count
    signals: SparkFailureSignals
    task_end_count: Count
    task_end_reasons: Annotated[tuple[TaskReasonCount, ...], Field(max_length=32)]
    reasons_omitted: Count
    evidence: Annotated[tuple[SparkEventEvidence, ...], Field(max_length=20)]
    evidence_omitted: Count
    coverage: SparkEventCoverage


class SparkEventQueryResult(SparkModel):
    snapshot: SparkSnapshot
    matched_count: Count
    task_end_count: Count
    task_end_reasons: Annotated[tuple[TaskReasonCount, ...], Field(max_length=32)]
    reasons_omitted: Count
    events: Annotated[tuple[SparkEventEvidence, ...], Field(max_length=20)]
    returned_count: Annotated[int, Field(ge=0, le=20)]
    next_after_line: PhysicalLine | None
    coverage: SparkEventCoverage
