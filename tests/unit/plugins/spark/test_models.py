"""Closed Spark request and file result contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


@pytest.mark.parametrize("application", ["application_1_42", "application_1700000000000_0042"])
def test_request_defaults(application: str) -> None:
    from mcp_stdio.plugins.spark.models import FetchRequest

    request = FetchRequest(application_id=application)
    assert request.attempt_id is None
    assert request.refresh is False


@pytest.mark.parametrize(
    "values",
    [
        {"application_id": "application_١_1"},
        {"application_id": "../app"},
        {"application_id": "application_1_1", "attempt_id": ""},
        {"application_id": "application_1_1", "attempt_id": "../1"},
        {"application_id": "application_1_1", "refresh": "true"},
        {"application_id": "application_1_1", "cache_policy": "offline"},
    ],
)
def test_invalid_request(values: dict[str, object]) -> None:
    from mcp_stdio.plugins.spark.models import FetchRequest

    with pytest.raises(ValidationError):
        FetchRequest.model_validate(values)


def test_result_exact_shape_and_sorting() -> None:
    from mcp_stdio.plugins.spark.models import SparkEventLogFetchResult, SparkEventLogFile

    def file(attempt: str | None) -> SparkEventLogFile:
        return SparkEventLogFile(
            attempt_id=attempt,
            local_path="/cache/eventlog.jsonl",
            spark_version="2.4.7",
            size_bytes=10,
            sha256="a" * 64,
            source_sha256="b" * 64,
            event_count=2,
            application_end_seen=False,
        )

    result = SparkEventLogFetchResult(
        application_id="application_1_42",
        requested_attempt_id=None,
        cache_hit=False,
        downloaded_at="2026-10-12T08:00:00Z",
        manifest_path="/cache/manifest.json",
        files=(file("2"), file(None), file("1")),
    )
    assert [f.attempt_id for f in result.files] == [None, "1", "2"]
    assert set(result.model_dump()) == {
        "application_id",
        "requested_attempt_id",
        "cache_hit",
        "downloaded_at",
        "manifest_path",
        "files",
    }
    with pytest.raises(ValidationError):
        file("bad/attempt")
