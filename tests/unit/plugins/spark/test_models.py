"""Closed Spark request and file result contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mcp_stdio.plugins.spark import inspection_models as models


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


def query_values(**overrides: object) -> dict[str, object]:
    return {
        "manifest_path": "/cache/manifest.json",
        "attempt_id": None,
        "expected_sha256": "a" * 64,
        **overrides,
    }


def test_inspect_requires_explicit_nullable_attempt() -> None:
    request = models.InspectRequest(manifest_path="/cache/manifest.json", attempt_id=None)
    assert request.model_dump() == {"manifest_path": "/cache/manifest.json", "attempt_id": None}
    assert models.InspectRequest.model_json_schema()["required"] == ["manifest_path", "attempt_id"]
    with pytest.raises(ValidationError):
        models.InspectRequest.model_validate({"manifest_path": "/cache/manifest.json"})


@pytest.mark.parametrize(
    "overrides",
    [
        {"manifest_path": "relative/manifest.json"},
        {"manifest_path": "/cache/\x00manifest"},
        {"manifest_path": "/" + "a" * 4096},
        {"manifest_path": 1},
        {"attempt_id": ""},
        {"attempt_id": "bad/attempt"},
        {"attempt_id": False},
        {"extra": "no"},
    ],
)
def test_inspect_rejects_invalid_input(overrides: dict[str, object]) -> None:
    values = {"manifest_path": "/cache/manifest.json", "attempt_id": None, **overrides}
    with pytest.raises(ValidationError):
        models.InspectRequest.model_validate(values)


def test_query_exact_defaults_and_direct_filters() -> None:
    request = models.QueryRequest.model_validate(query_values())
    assert request.model_dump() == {
        **query_values(),
        "event_types": None,
        "execution_id": None,
        "job_id": None,
        "stage_id": None,
        "stage_attempt_id": None,
        "task_id": None,
        "executor_id": None,
        "task_end_reason": None,
        "lines": None,
        "after_line": 0,
        "limit": 20,
        "max_detail_chars": 2048,
    }
    query = models.QueryRequest.model_validate(
        query_values(
            event_types=["SparkListenerTaskEnd"],
            execution_id=2**63 - 1,
            job_id=0,
            stage_id=3,
            stage_attempt_id=1,
            task_id=5,
            executor_id="driver",
            task_end_reason="UNKNOWN",
            lines=[1, 2**63 - 1],
            after_line=2**63 - 1,
            limit=1,
        )
    )
    assert query.event_types == ["SparkListenerTaskEnd"]
    assert query.job_id == 0
    assert query.stage_id == 3
    assert query.lines == [1, 2**63 - 1]


@pytest.mark.parametrize(
    "field",
    [
        "execution_id",
        "job_id",
        "stage_id",
        "stage_attempt_id",
        "task_id",
        "after_line",
        "limit",
        "max_detail_chars",
    ],
)
@pytest.mark.parametrize("value", [True, "1", 1.0, -1, 2**63])
def test_query_rejects_non_strict_or_unbounded_numbers(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        models.QueryRequest.model_validate(query_values(**{field: value}))


@pytest.mark.parametrize(
    "overrides",
    [
        {"expected_sha256": "A" * 64},
        {"expected_sha256": "a" * 63},
        {"expected_sha256": "g" * 64},
        {"event_types": []},
        {"event_types": ["Event"] * 17},
        {"event_types": ("Event",)},
        {"event_types": [1]},
        {"event_types": [""]},
        {"event_types": ["e" * 513]},
        {"event_types": ["bad\nEvent"]},
        {"lines": []},
        {"lines": list(range(1, 22))},
        {"lines": (1,)},
        {"lines": [True]},
        {"lines": ["1"]},
        {"lines": [0]},
        {"lines": [2**63]},
        {"lines": [1, 1]},
        {"stage_attempt_id": 0},
        {"executor_id": ""},
        {"executor_id": "bad/executor"},
        {"executor_id": "e" * 129},
        {"executor_id": 1},
        {"task_end_reason": ""},
        {"task_end_reason": "r" * 129},
        {"task_end_reason": "bad\x7freason"},
        {"limit": 0},
        {"limit": 21},
        {"max_detail_chars": 0},
        {"max_detail_chars": 32769},
        {"max_detail_chars": 2049},
        {"max_detail_chars": 2049, "lines": [1]},
        {"max_detail_chars": 2049, "lines": [1, 2], "limit": 1},
        {"unapproved_filter": 1},
    ],
)
def test_query_rejects_invalid_contract(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        models.QueryRequest.model_validate(query_values(**overrides))


def test_query_permits_single_line_detail_expansion() -> None:
    query = models.QueryRequest.model_validate(
        query_values(lines=[12], limit=1, max_detail_chars=32768)
    )
    assert query.max_detail_chars == 32768


def evidence_values() -> dict[str, object]:
    return {
        "ref": {"sha256": "a" * 64, "line": 1},
        "event_type": "SparkListenerTaskEnd",
        "ids": {
            "execution_id": None,
            "job_id": None,
            "stage_id": 0,
            "stage_attempt_id": 0,
            "task_id": 1,
            "executor_id": "3",
        },
        "details": "synthetic evidence",
        "details_truncated": False,
    }


def test_inspection_and_query_exact_result_shapes() -> None:
    snapshot = models.SparkSnapshot(
        application_id="application_1_42", attempt_id=None, sha256="a" * 64
    )
    evidence = models.SparkEventEvidence.model_validate(evidence_values())
    coverage = models.SparkEventCoverage(application_start_seen=True, application_end_seen=False)
    reasons = (models.TaskReasonCount(reason="Success", count=2),)
    result = models.SparkEventLogInspectionResult(
        snapshot=snapshot,
        spark_version=None,
        event_count=2,
        event_types=(models.EventTypeCount(event_type="SparkListenerTaskEnd", count=2),),
        event_types_omitted=0,
        signals=models.SparkFailureSignals(
            job_failed_events=0,
            stage_failure_events=0,
            task_non_success_events=0,
            executor_removed_events=0,
        ),
        task_end_count=2,
        task_end_reasons=reasons,
        reasons_omitted=0,
        evidence=(evidence,),
        evidence_omitted=0,
        coverage=coverage,
    )
    assert set(result.model_dump()) == {
        "snapshot",
        "spark_version",
        "event_count",
        "event_types",
        "event_types_omitted",
        "signals",
        "task_end_count",
        "task_end_reasons",
        "reasons_omitted",
        "evidence",
        "evidence_omitted",
        "coverage",
    }
    query = models.SparkEventQueryResult(
        snapshot=snapshot,
        matched_count=2,
        task_end_count=2,
        task_end_reasons=reasons,
        reasons_omitted=0,
        events=(evidence,),
        returned_count=1,
        next_after_line=1,
        coverage=coverage,
    )
    assert set(query.model_dump()) == {
        "snapshot",
        "matched_count",
        "task_end_count",
        "task_end_reasons",
        "reasons_omitted",
        "events",
        "returned_count",
        "next_after_line",
        "coverage",
    }
    assert set(evidence.model_dump()) == {
        "ref",
        "event_type",
        "ids",
        "details",
        "details_truncated",
    }
    assert set(coverage.model_dump()) == {"application_start_seen", "application_end_seen"}
    assert isinstance(query.events, tuple)
    assert isinstance(result.task_end_reasons, tuple)
    assert models.SparkEventQueryResult.model_validate_json(query.model_dump_json()) == query
    with pytest.raises(ValidationError):
        result.event_count = 10
    for field, values in [
        ("evidence", (evidence,) * 21),
        ("event_types", result.event_types * 33),
        ("task_end_reasons", reasons * 33),
    ]:
        with pytest.raises(ValidationError):
            models.SparkEventLogInspectionResult.model_validate(
                {**result.model_dump(), field: values}
            )


@pytest.mark.parametrize(
    "values",
    [
        {"sha256": "a" * 64, "line": 0},
        {"sha256": "a" * 64, "line": True},
        {"sha256": "a" * 64, "line": "1"},
        {"sha256": "a" * 64, "line": 2**63},
        {"sha256": "A" * 64, "line": 1},
        {"sha256": "a" * 64, "line": 1, "raw_path": "/cache/log"},
    ],
)
def test_event_ref_rejects_unsafe_or_unbounded_values(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        models.SparkEventRef.model_validate(values)


def test_event_ids_are_exact_nullable_scalar_observations() -> None:
    model = models.SparkEventIds
    values = {
        field: None
        for field in (
            "execution_id",
            "job_id",
            "stage_id",
            "stage_attempt_id",
            "task_id",
            "executor_id",
        )
    }
    assert model.model_validate(values).model_dump() == values
    for invalid in [
        {"stage_id": [1]},
        {"job_id": True},
        {"task_id": -1},
        {"execution_id": 2**63},
        {"executor_id": "../3"},
        {"inferred_id": 1},
    ]:
        with pytest.raises(ValidationError):
            model.model_validate({**values, **invalid})
    with pytest.raises(ValidationError):
        model.model_validate({})


def test_evidence_rejects_extra_fields_and_unbounded_details() -> None:
    model = models.SparkEventEvidence
    for invalid in [
        {"details": "d" * 32769},
        {"event_type": ""},
        {"details_truncated": "false"},
        {"extra": "no"},
    ]:
        with pytest.raises(ValidationError):
            model.model_validate({**evidence_values(), **invalid})


def test_inspection_port_is_async_with_explicit_deadline() -> None:
    import inspect
    from typing import get_type_hints

    from mcp_stdio.plugins.spark import gateway

    port = gateway.SparkInspectionGateway
    for name, request, result in [
        ("inspect", models.InspectRequest, models.SparkEventLogInspectionResult),
        ("query", models.QueryRequest, models.SparkEventQueryResult),
    ]:
        method = getattr(port, name)
        assert inspect.iscoroutinefunction(method)
        assert (
            inspect.signature(method).parameters["deadline"].kind is inspect.Parameter.KEYWORD_ONLY
        )
        assert get_type_hints(method) == {"request": request, "deadline": float, "return": result}
    assert inspect.iscoroutinefunction(port.close)
