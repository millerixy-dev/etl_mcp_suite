"""Closed, transport-independent Spark input and result models."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def validate_application_id(value: str) -> str:
    if len(value) > 128 or not re.fullmatch(r"application_[0-9]+_[0-9]+", value):
        raise ValueError("invalid application ID")
    return value


def validate_attempt_id(value: str | None) -> str | None:
    if value is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("invalid attempt ID")
    return value


def validate_local_path(value: str) -> str:
    if (
        not value.startswith("/")
        or len(value) > 4096
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise ValueError("invalid local evidence path")
    return value


class SparkModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class FetchRequest(SparkModel):
    application_id: str
    attempt_id: str | None = None
    refresh: bool = False

    _application = field_validator("application_id")(validate_application_id)
    _attempt = field_validator("attempt_id")(validate_attempt_id)


class SparkEventLogFile(SparkModel):
    attempt_id: str | None
    local_path: str
    spark_version: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,128}$")]
    size_bytes: Annotated[int, Field(ge=1)]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    source_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    event_count: Annotated[int, Field(ge=1)]
    application_end_seen: bool

    _attempt = field_validator("attempt_id")(validate_attempt_id)

    _path = field_validator("local_path")(validate_local_path)


class SparkEventLogFetchResult(SparkModel):
    application_id: str
    requested_attempt_id: str | None
    cache_hit: bool
    downloaded_at: str
    manifest_path: str
    files: Annotated[tuple[SparkEventLogFile, ...], Field(min_length=1, max_length=16)]

    _application = field_validator("application_id")(validate_application_id)
    _attempt = field_validator("requested_attempt_id")(validate_attempt_id)
    _path = field_validator("manifest_path")(validate_local_path)

    @field_validator("downloaded_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        if len(value) > 40 or not value.endswith("Z"):
            raise ValueError("download time must be UTC RFC3339")
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    @model_validator(mode="after")
    def sort_files(self) -> SparkEventLogFetchResult:
        attempts = [item.attempt_id for item in self.files]
        if len(set(attempts)) != len(attempts):
            raise ValueError("duplicate attempt")
        if self.requested_attempt_id is not None and attempts != [self.requested_attempt_id]:
            raise ValueError("attempt does not match selection")
        object.__setattr__(
            self,
            "files",
            tuple(
                sorted(
                    self.files,
                    key=lambda item: (item.attempt_id is not None, item.attempt_id or ""),
                )
            ),
        )
        return self
