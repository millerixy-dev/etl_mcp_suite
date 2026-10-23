"""Strict transport-independent container-log contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator

from mcp_stdio.plugins.spark.models import (
    SparkEventLogFetchResult,
    SparkModel,
    validate_application_id,
    validate_local_path,
)

LogType = Literal["stdout", "stderr"]
LogAttempt = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,9}$")]
LogExecutor = Annotated[str, Field(pattern=r"^(driver|0|[1-9][0-9]{0,19})$")]
TailBytes = Annotated[int, Field(ge=1, le=1048576)]


class SparkExecutorLogRequest(SparkModel):
    application_id: str
    attempt_id: LogAttempt
    executor_id: LogExecutor
    log_type: LogType = "stderr"
    tail_bytes: TailBytes = 65536

    _application = field_validator("application_id")(validate_application_id)


class SparkExecutorLogFetchResult(SparkModel):
    application_id: str
    attempt_id: LogAttempt
    executor_id: LogExecutor
    container_id: Annotated[
        str, Field(pattern=r"^container_(e[0-9]+_)?[0-9]+_[0-9]+_[0-9]+_[0-9]+$", max_length=256)
    ]
    log_type: LogType
    requested_tail_bytes: TailBytes
    fetched_at: str
    coverage: Literal["tail", "complete", "unknown"]
    local_path: str
    size_bytes: Annotated[int, Field(ge=0, le=1048576)]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    manifest_path: str

    _application = field_validator("application_id")(validate_application_id)
    _paths = field_validator("local_path", "manifest_path")(validate_local_path)
    @field_validator("fetched_at")
    @classmethod
    def validate_time(cls, value: str) -> str:
        return SparkEventLogFetchResult.validate_timestamp(value)
