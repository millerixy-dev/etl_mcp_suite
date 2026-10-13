"""Whole-snapshot overview of exclusively synthetic private evidence."""

# ruff: noqa: ASYNC240 -- small local synthetic fixtures
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path

import pytest

from mcp_stdio.plugins.spark.config import SparkSettings
from mcp_stdio.plugins.spark.inspection import SparkInspectionAdapter
from mcp_stdio.plugins.spark.inspection_events import event_details
from mcp_stdio.plugins.spark.inspection_models import InspectRequest
from tests.unit.plugins.spark.fixtures import encode, events, private_manifest


def snapshot(
    tmp_path: Path,
    records: list[dict[str, object]],
    *,
    end: bool = True,
    secrets: tuple[str, ...] = (),
):
    manifest, body = private_manifest(tmp_path / "l3", (None,))
    records = events(None)[:2] + records + (events(None)[2:] if end else [])
    raw = encode(records)
    entry = body["files"][0]
    Path(entry["local_path"]).write_bytes(raw)
    entry.update(
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        event_count=len(records),
        application_end_seen=end,
    )
    manifest.write_text(json.dumps(body))
    settings = SparkSettings(
        history_server_url="https://history.example", cache_dir=str(tmp_path / "l3")
    )
    return SparkInspectionAdapter(settings, secrets), InspectRequest(
        manifest_path=str(manifest), attempt_id=None
    )


def task(reason: object) -> dict[str, object]:
    return {"Event": "SparkListenerTaskEnd", "Task End Reason": {"Reason": reason}}


@pytest.mark.asyncio
async def test_full_counts_and_late_high_priority_samples(tmp_path: Path):
    records: list[dict[str, object]] = [task("FetchFailed") for _ in range(25)]
    records.extend(
        [
            {"Event": "SparkListenerExecutorRemoved", "Removed Reason": "unknown"},
            {"Event": "SparkListenerStageCompleted", "Stage Info": {"Failure Reason": "failed"}},
            {"Event": "SparkListenerJobEnd", "Job Result": {"Result": "JobFailed"}},
        ]
    )
    adapter, request = snapshot(tmp_path, records)
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    result = await adapter.inspect(request, deadline=time.monotonic() + 10)
    assert result.event_count == 31
    assert result.task_end_count == 25
    assert result.signals.model_dump() == dict(
        job_failed_events=1,
        stage_failure_events=1,
        task_non_success_events=25,
        executor_removed_events=1,
    )
    assert len(result.evidence) == 20 and result.evidence_omitted == 8
    assert [item.ref.line for item in result.evidence[:3]] == [30, 29, 3]
    assert result.evidence[0].ref.sha256 == result.snapshot.sha256
    assert result.task_end_reasons[0].reason == "FetchFailed"
    assert result.task_end_reasons[0].count == 25
    assert result.coverage.application_end_seen
    assert before == sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    await adapter.close()


@pytest.mark.asyncio
async def test_bounded_categories_deterministic_ties(tmp_path: Path):
    records: list[dict[str, object]] = [{"Event": f"Vendor{i:02}"} for i in reversed(range(40))]
    records.extend([task(f"Reason{i:02}") for i in reversed(range(40))])
    adapter, request = snapshot(tmp_path, records)
    result = await adapter.inspect(request, deadline=time.monotonic() + 10)
    assert len(result.event_types) == 32 and result.event_types_omitted == 12
    assert result.event_types[0].event_type == "SparkListenerTaskEnd"
    assert [item.reason for item in result.task_end_reasons] == [f"Reason{i:02}" for i in range(32)]
    assert result.reasons_omitted == 8
    assert result.evidence_omitted == 20


@pytest.mark.asyncio
async def test_unknown_invalid_reasons_and_cancellations_are_observations(tmp_path: Path):
    records: list[dict[str, object]] = [
        task(value)
        for value in (
            None,
            "",
            12,
            True,
            "bad\nreason",
            "Success",
            "UNKNOWN",
            "TaskKilled",
            "Resubmitted",
        )
    ]
    records.extend(
        [
            {"Event": "SparkListenerTaskEnd"},
            {
                "Event": "SparkListenerJobEnd",
                "Job ID": True,
                "Job Result": {"Result": "JobSucceeded"},
            },
        ]
    )
    adapter, request = snapshot(tmp_path, records, end=False)
    result = await adapter.inspect(request, deadline=time.monotonic() + 10)
    assert result.task_end_count == 10
    assert result.signals.task_non_success_events == 3
    assert {item.reason: item.count for item in result.task_end_reasons}["UNKNOWN"] == 7
    assert [item.ref.line for item in result.evidence] == [9, 10, 11]
    assert not result.coverage.application_end_seen
    assert all(item.ids.job_id is None for item in result.evidence)


@pytest.mark.asyncio
async def test_fallback_ending_entry_order_and_empty_candidates(tmp_path: Path):
    records: list[dict[str, object]] = [
        {
            "Event": "org.apache.spark.sql.execution.ui.SparkListenerSQLExecutionEnd",
            "executionId": 9,
            "time": 5,
        },
        {
            "Event": "SparkListenerJobEnd",
            "Job ID": 7,
            "Completion Time": 6,
            "Job Result": {"Result": "JobSucceeded"},
        },
    ]
    adapter, request = snapshot(tmp_path, records)
    result = await adapter.inspect(request, deadline=time.monotonic() + 10)
    assert [item.ref.line for item in result.evidence] == [3, 4, 5]
    assert result.evidence[0].ids.execution_id == 9
    assert result.evidence[1].ids.job_id == 7
    adapter2, request2 = snapshot(tmp_path / "empty", [{"Event": "VendorEvent"}], end=False)
    empty = await adapter2.inspect(request2, deadline=time.monotonic() + 10)
    assert empty.evidence == () and empty.evidence_omitted == 0


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        (
            {
                "Event": "SparkListenerJobStart",
                "Stage IDs": [2],
                "Properties": {"spark.sql.execution.id": "8", "other": "omit"},
            },
            'Stage IDs: [2]\nProperties: {"spark.sql.execution.id": "8"}',
        ),
        (
            {
                "Event": "SparkListenerStageCompleted",
                "Stage Info": {"Stage Name": "中文", "Failure Reason": "oops", "Other": "omit"},
            },
            'Stage Name: "中文"\nFailure Reason: "oops"',
        ),
        (
            {
                "Event": "SparkListenerTaskEnd",
                "Task Info": {"Task ID": 3},
                "Task End Reason": {"Reason": "FetchFailed"},
                "Task Metrics": {"Executor Run Time": 7},
            },
            'Task Info: {"Task ID": 3}\nTask End Reason: {"Reason": "FetchFailed"}'
            '\nTask Metrics: {"Executor Run Time": 7}',
        ),
        (
            {
                "Event": "SparkListenerExecutorAdded",
                "Executor Info": {"Host": "host", "Total Cores": 4, "Other": "omit"},
            },
            'Executor Info: {"Host": "host", "Total Cores": 4}',
        ),
        (
            {"Event": "Vendor", "arbitrary": {"x": "中文"}},
            '{"Event": "Vendor", "arbitrary": {"x": "中文"}}',
        ),
    ],
)
def test_fixed_projection_and_unknown_vendor(event: dict[str, object], expected: str):
    assert event_details(event, (), 2048) == (expected, False)


def test_text_head_tail_and_direct_ids_unknown_fields():
    event: dict[str, object] = {
        "Event": "SparkListenerTaskEnd",
        "Task End Reason": {"Reason": "ExceptionFailure", "Description": "x" * 4000},
        "Task Info": {"Task ID": "3", "Executor ID": "bad value"},
        "unselected": "omit",
    }
    full, truncated = event_details(event, (), 32768)
    assert not truncated and "unselected" not in full
    short, truncated = event_details(event, (), 2048)
    assert truncated and short == full[:1024] + full[-1024:]


def test_redaction_before_and_after_splice():
    event: dict[str, object] = {
        "Event": "Vendor",
        "text": "private-value password=hunter token=tokenvalue Cookie: opaque",
    }
    text, _ = event_details(event, ("private-value",), 2048)
    assert all(secret not in text for secret in ("private-value", "hunter", "tokenvalue", "opaque"))
    event: dict[str, object] = {"Event": "Vendor", "text": "abcdef" + "x" * 200 + "uvwxyz"}
    full, _ = event_details(event, (), 2048)
    joined = full[:30] + full[-30:]
    seam_secret = full[25:30] + full[-30:-25]
    text, truncated = event_details(event, (seam_secret,), 60)
    assert truncated and seam_secret not in text and text != joined
    assert len(text) <= 60


@pytest.mark.asyncio
async def test_close_cancels_and_awaits_active_scan(tmp_path: Path):
    adapter, request = snapshot(tmp_path, [task("Success") for _ in range(1000)])
    scan = asyncio.create_task(adapter.inspect(request, deadline=time.monotonic() + 10))
    await asyncio.sleep(0)
    await adapter.close()
    assert scan.done() and scan.cancelled()
    await adapter.close()


@pytest.mark.asyncio
async def test_bounded_fallback_omissions_and_invalid_failure_fields(tmp_path: Path):
    records: list[dict[str, object]] = [
        {"Event": "SparkListenerStageCompleted", "Stage Info": {"Failure Reason": value}}
        for value in (None, False, "", 3)
    ]
    records.extend(
        [
            {"Event": "SparkListenerJobEnd", "Job Result": {"Result": "JobSucceeded"}}
            for _ in range(25)
        ]
    )
    adapter, request = snapshot(tmp_path, records)
    result = await adapter.inspect(request, deadline=time.monotonic() + 10)
    assert result.signals.stage_failure_events == 0
    assert [item.ref.line for item in result.evidence] == list(range(7, 27))
    assert result.evidence_omitted == 6


@pytest.mark.asyncio
async def test_direct_nullable_ids_and_secret_projection_in_result(tmp_path: Path):
    record: dict[str, object] = {
        "Event": "SparkListenerTaskEnd",
        "Stage ID": 3,
        "Stage Attempt ID": 1,
        "Job ID": "4",
        "executionId": True,
        "Task Info": {"Task ID": 7, "Executor ID": "executor_3"},
        "Task End Reason": {
            "Reason": "ExceptionFailure",
            "Description": "private-value token=secret-value",
        },
        "unselected": "x" * 100000,
    }
    adapter, request = snapshot(tmp_path, [record], secrets=("private-value",))
    result = await adapter.inspect(request, deadline=time.monotonic() + 10)
    evidence = result.evidence[0]
    assert evidence.ids.model_dump() == dict(
        execution_id=None,
        job_id=None,
        stage_id=3,
        stage_attempt_id=1,
        task_id=7,
        executor_id="executor_3",
    )
    assert "private-value" not in result.model_dump_json()
    assert "secret-value" not in result.model_dump_json()
    assert not evidence.details_truncated


def test_other_fixed_fields_and_environment_redaction():
    records: list[tuple[dict[str, object], str]] = [
        (
            {
                "Event": "SparkListenerJobEnd",
                "Completion Time": 9,
                "Job Result": {"Result": "JobFailed", "Exception": {"Message": "error"}},
                "Ignore": 1,
            },
            'Completion Time: 9\nJob Result: {"Exception": {"Message": "error"}, '
            '"Result": "JobFailed"}',
        ),
        (
            {
                "Event": "SparkListenerApplicationStart",
                "Timestamp": 1,
                "App Name": "name",
                "App ID": "application_1_42",
                "App Attempt ID": None,
            },
            'Timestamp: 1\nApp Name: "name"\nApp ID: "application_1_42"\nApp Attempt ID: null',
        ),
        (
            {
                "Event": "org.apache.spark.sql.execution.ui.SparkListenerSQLExecutionStart",
                "executionId": 3,
                "time": 4,
                "description": "sql",
                "details": "info",
                "physicalPlanDescription": "plan",
                "Ignore": 1,
            },
            'executionId: 3\ntime: 4\ndescription: "sql"\ndetails: "info"\n'
            'physicalPlanDescription: "plan"',
        ),
        (
            {
                "Event": "SparkListenerEnvironmentUpdate",
                "Spark Properties": {"spark.master": "yarn", "unsafe": "opaque"},
                "System Properties": {"password": "opaque"},
            },
            'Spark Properties: {"spark.master": "yarn", "unsafe": "[REDACTED]"}',
        ),
    ]
    for event, expected in records:
        assert event_details(event, ()) == (expected, False)


def query_request(request: InspectRequest, **filters: object):
    from mcp_stdio.plugins.spark.inspection_models import QueryRequest

    body = json.loads(Path(request.manifest_path).read_text())
    return QueryRequest.model_validate(
        {**request.model_dump(), "expected_sha256": body["files"][0]["sha256"], **filters}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filters", "lines"),
    [
        ({"execution_id": 0}, [3, 7]),
        ({"job_id": 0}, [3, 4]),
        ({"stage_id": 0}, [5, 6, 8]),
        ({"stage_id": 0, "stage_attempt_id": 0}, [5, 6]),
        ({"task_id": 0}, [6]),
        ({"executor_id": "e0"}, [6, 9]),
        ({"stage_id": 0, "task_end_reason": "FetchFailed"}, [6]),
        ({"task_end_reason": "UNKNOWN"}, [8]),
        ({"event_types": ["Vendor", "SparkListenerTaskEnd"], "lines": [6, 8, 10]}, [6, 8, 10]),
        ({"event_types": ["SparkListenerSQLExecutionStart"]}, []),
        ({"job_id": 99}, []),
        ({"execution_id": 0, "job_id": 0, "lines": [3, 4]}, [3]),
        (
            {
                "stage_id": 0,
                "stage_attempt_id": 0,
                "task_id": 0,
                "executor_id": "e0",
                "task_end_reason": "FetchFailed",
                "event_types": ["SparkListenerTaskEnd"],
                "lines": [6],
            },
            [6],
        ),
    ],
)
async def test_query_direct_filters_without_relation_expansion(
    tmp_path: Path, filters: dict[str, object], lines: list[int]
):
    adapter, request = snapshot(
        tmp_path,
        [
            {
                "Event": "SparkListenerJobStart",
                "Job ID": 0,
                "Stage IDs": [0],
                "Properties": {"spark.sql.execution.id": "0"},
            },
            {"Event": "SparkListenerJobEnd", "Job ID": 0},
            {
                "Event": "SparkListenerStageSubmitted",
                "Stage Info": {"Stage ID": 0, "Stage Attempt ID": 0},
            },
            {
                **task("FetchFailed"),
                "Stage ID": 0,
                "Stage Attempt ID": 0,
                "Task Info": {"Task ID": 0, "Executor ID": "e0"},
            },
            {
                "Event": "org.apache.spark.sql.execution.ui.SparkListenerSQLExecutionStart",
                "executionId": 0,
            },
            {"Event": "SparkListenerTaskEnd", "Stage ID": 0, "Stage Attempt ID": 1},
            {"Event": "SparkListenerBlockUpdated", "Block Manager ID": {"Executor ID": "e0"}},
            {"Event": "Vendor", "Task End Reason": {"Reason": "UNKNOWN"}},
        ],
    )
    result = await adapter.query(query_request(request, **filters), deadline=time.monotonic() + 10)
    assert [event.ref.line for event in result.events] == lines
    assert result.matched_count == len(lines)
    assert result.returned_count == len(lines) and result.next_after_line is None
    assert set(result.model_dump()) == {
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


@pytest.mark.asyncio
async def test_query_all_matches_counted_before_pages_and_rare_reason(tmp_path: Path):
    adapter, request = snapshot(
        tmp_path, [task("Success") for _ in range(45)] + [task("FetchFailed")]
    )
    refs: list[int] = []
    after = 0
    while True:
        result = await adapter.query(
            query_request(request, event_types=["SparkListenerTaskEnd"], after_line=after),
            deadline=time.monotonic() + 10,
        )
        assert result.matched_count == result.task_end_count == 46
        assert {item.reason: item.count for item in result.task_end_reasons} == {
            "Success": 45,
            "FetchFailed": 1,
        }
        assert result.returned_count == len(result.events)
        refs.extend(item.ref.line for item in result.events)
        assert all(item.ref.sha256 == result.snapshot.sha256 for item in result.events)
        if result.next_after_line is None:
            break
        assert result.next_after_line == result.events[-1].ref.line
        after = result.next_after_line
    assert refs == list(range(3, 49))
    empty = await adapter.query(
        query_request(request, after_line=100), deadline=time.monotonic() + 10
    )
    assert empty.events == () and empty.next_after_line is None and empty.matched_count == 49
    rare = await adapter.query(
        query_request(request, task_end_reason="FetchFailed"), deadline=time.monotonic() + 10
    )
    assert [event.ref.line for event in rare.events] == [48]
    selected = await adapter.query(
        query_request(request, lines=[3, 48], after_line=3, limit=1), deadline=time.monotonic() + 10
    )
    assert selected.matched_count == selected.task_end_count == 2
    assert selected.next_after_line is None


@pytest.mark.asyncio
async def test_query_reason_category_bound_and_missing_field(tmp_path: Path):
    adapter, request = snapshot(
        tmp_path,
        [task(f"R{i:02}") for i in reversed(range(40))]
        + [{"Event": "SparkListenerTaskEnd", "Task Info": {"Task ID": "0"}}],
    )
    result = await adapter.query(
        query_request(request, event_types=["SparkListenerTaskEnd"]), deadline=time.monotonic() + 10
    )
    assert result.task_end_count == 41 and result.reasons_omitted == 9
    assert [item.reason for item in result.task_end_reasons] == [f"R{i:02}" for i in range(32)]
    missing = await adapter.query(query_request(request, task_id=0), deadline=time.monotonic() + 10)
    assert missing.matched_count == missing.task_end_count == 0 and missing.task_end_reasons == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("length", [4000, 40000])
async def test_query_ref_reread_and_single_text_bound(tmp_path: Path, length: int):
    adapter, request = snapshot(
        tmp_path,
        [
            {
                **task("ExceptionFailure"),
                "Task End Reason": {"Reason": "ExceptionFailure", "Description": "x" * length},
            }
        ],
    )
    first = await adapter.query(query_request(request, lines=[3]), deadline=time.monotonic() + 10)
    expanded = await adapter.query(
        query_request(request, lines=[3], limit=1, max_detail_chars=32768),
        deadline=time.monotonic() + 10,
    )
    assert first.events[0].ref == expanded.events[0].ref
    assert first.events[0].details_truncated and len(first.events[0].details) == 2048
    assert expanded.events[0].details_truncated == (length > 32768)
    assert len(expanded.events[0].details) <= 32768


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["expected_hash", "digest", "tail"])
async def test_query_rejects_corruption_after_page_fills(tmp_path: Path, corruption: str):
    from mcp_stdio.plugins.spark.gateway import SparkGatewayError

    adapter, request = snapshot(tmp_path, [task("Success") for _ in range(25)])
    query = query_request(request, limit=1)
    body = json.loads(Path(request.manifest_path).read_text())
    if corruption == "expected_hash":
        query = query.model_copy(update={"expected_sha256": "0" * 64})
    else:
        path = Path(body["files"][0]["local_path"])
        raw = path.read_bytes()
        if corruption == "digest":
            raw = raw.replace(b"Success", b"Failure", 1)
        else:
            raw = raw.rsplit(b"\n", 2)[0] + b"\n{broken\n"
            body["files"][0].update(size_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            Path(request.manifest_path).write_text(json.dumps(body))
            query = query_request(request, limit=1)
        path.write_bytes(raw)
    with pytest.raises(SparkGatewayError):
        await adapter.query(query, deadline=time.monotonic() + 10)


@pytest.mark.asyncio
async def test_query_cancel_and_shared_close_wait_for_both_scans(tmp_path: Path):
    adapter, request = snapshot(tmp_path, [task("Success") for _ in range(1000)])
    cancelled = asyncio.create_task(
        adapter.query(query_request(request), deadline=time.monotonic() + 10)
    )
    await asyncio.sleep(0)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    inspect = asyncio.create_task(adapter.inspect(request, deadline=time.monotonic() + 10))
    query = asyncio.create_task(
        adapter.query(query_request(request), deadline=time.monotonic() + 10)
    )
    await asyncio.sleep(0)
    await adapter.close()
    assert inspect.cancelled() and query.cancelled()
    with pytest.raises(asyncio.CancelledError):
        await adapter.query(query_request(request), deadline=time.monotonic() + 10)
