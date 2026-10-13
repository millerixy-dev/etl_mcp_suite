"""Fixed event measurements distinguish missing values from explicit zero."""

# ruff: noqa: ASYNC240 -- small local synthetic fixtures

import asyncio
import hashlib
import json
import socket
import time
from collections.abc import Sequence
from pathlib import Path

import pytest

from mcp_stdio.plugins.spark.gateway import SparkGatewayError
from mcp_stdio.plugins.spark.inspection_models import InspectRequest
from mcp_stdio.plugins.spark.metrics_events import metric_integer, task_metric_values
from mcp_stdio.plugins.spark.metrics_models import StageMetricsRequest
from tests.unit.plugins.spark.test_inspection import query_request, snapshot, task


def test_integer_accepts_zero_and_signed_64_max() -> None:
    assert metric_integer(0) == 0
    assert metric_integer(2**63 - 1) == 2**63 - 1


@pytest.mark.parametrize("value", [None, True, False, "1", 1.0, -1, 2**63, {}, []])
def test_integer_rejects_non_strict_or_out_of_range_values(value: object) -> None:
    assert metric_integer(value) is None


def test_extracts_six_named_metrics_and_preserves_zero() -> None:
    event: dict[str, object] = {
        "Task Info": {"Launch Time": 10, "Finish Time": 10},
        "Task Metrics": {
            "Executor Run Time": 0, "JVM GC Time": 2,
            "Input Metrics": {"Bytes Read": 3},
            "Shuffle Read Metrics": {
                "Remote Bytes Read": 4, "Local Bytes Read": 5, "Fetch Wait Time": 0,
            },
        },
    }
    assert task_metric_values(event).model_dump() == {
        "duration_ms": 0, "executor_run_time_ms": 0, "jvm_gc_time_ms": 2,
        "input_bytes": 3, "shuffle_read_bytes": 9, "shuffle_fetch_wait_ms": 0,
    }


@pytest.mark.parametrize("metrics", [None, [], "bad", {}, {"Input Metrics": True}])
def test_missing_metrics_does_not_erase_duration(metrics: object) -> None:
    values = task_metric_values({
        "Task Info": {"Launch Time": 0, "Finish Time": 1}, "Task Metrics": metrics,
    })
    assert values.duration_ms == 1
    assert list(values.model_dump().values())[1:] == [None] * 5


@pytest.mark.parametrize("start,end", [(0, 0), (2, 1), (-1, 1), (True, 2), (0, 2**63),
                                       ("0", 1), (0, 1.0), (None, 1)])
def test_invalid_timestamps_remain_unknown(start: object, end: object) -> None:
    assert task_metric_values({"Task Info": {
        "Launch Time": start, "Finish Time": end,
    }}).duration_ms is None


@pytest.mark.parametrize("value", [None, True, "0", 0.0, -1, 2**63])
def test_invalid_raw_metric_values_remain_unknown(value: object) -> None:
    metrics = {
        "Executor Run Time": value, "JVM GC Time": value,
        "Input Metrics": {"Bytes Read": value},
        "Shuffle Read Metrics": {
            "Remote Bytes Read": value, "Local Bytes Read": 0, "Fetch Wait Time": value,
        },
    }
    assert list(task_metric_values({"Task Metrics": metrics}).model_dump().values()) == [None] * 6


@pytest.mark.parametrize("shuffle", [{}, {"Remote Bytes Read": 0}, {"Local Bytes Read": 0}])
def test_shuffle_requires_both_components(shuffle: dict[str, object]) -> None:
    assert task_metric_values({"Task Metrics": {
        "Shuffle Read Metrics": shuffle,
    }}).shuffle_read_bytes is None


def test_shuffle_sum_can_exceed_signed_64() -> None:
    assert task_metric_values({"Task Metrics": {"Shuffle Read Metrics": {
        "Remote Bytes Read": 2**63 - 1, "Local Bytes Read": 2**63 - 1,
    }}}).shuffle_read_bytes == 2**64 - 2


def test_absent_task_info_and_metrics_are_unknown() -> None:
    assert list(task_metric_values({}).model_dump().values()) == [None] * 6


@pytest.mark.parametrize("reason,expected", [
    ({"Reason": "Success"}, "success"), ({"Reason": "UNKNOWN"}, "non_success"),
    ({"Reason": "ExceptionFailure"}, "non_success"), ({"Reason": "success"}, "non_success"),
    ({"Reason": ""}, "unknown"), ({"Reason": "Success\n"}, "unknown"),
    ({"Reason": "x" * 129}, "unknown"), ({"Reason": True}, "unknown"),
    ({}, "unknown"), (None, "unknown"), ("Success", "unknown"),
])
def test_classifies_explicit_reasons(reason: object, expected: str) -> None:
    from mcp_stdio.plugins.spark.metrics_events import task_outcome
    assert task_outcome({"Task End Reason": reason}) == expected


@pytest.mark.parametrize("samples,successful,expected", [
    ([], 0, (0, 0, None, None, None, None)),
    ([], 2, (0, 2, None, None, None, None)),
    ([0], 2, (1, 1, 0, 0, 0, 0)),
    ([900, 100], 3, (2, 1, 100, 100, 900, 900)),
    (list(range(1, 21)), 20, (20, 0, 1, 10, 19, 20)),
    ([2**64 - 2], 1, (1, 0, 2**64 - 2, 2**64 - 2, 2**64 - 2, 2**64 - 2)),
])
def test_nearest_rank(samples: list[int], successful: int, expected: tuple[object, ...]) -> None:
    from mcp_stdio.plugins.spark.metrics_events import metric_distribution
    original = list(samples)
    assert tuple(metric_distribution(samples, successful).model_dump().values()) == expected
    assert samples == original


def test_retry_and_speculative_successes_remain_separate_samples() -> None:
    from mcp_stdio.plugins.spark.metrics_events import metric_distribution, task_outcome
    events: list[dict[str, object]] = [
        {"Task End Reason": {"Reason": reason}, "Task Info": {
            "Index": 0, "Attempt": attempt, "Speculative": speculative,
            "Launch Time": 1, "Finish Time": 11,
        }}
        for reason, attempt, speculative in [
            ("ExceptionFailure", 0, False), ("Success", 1, False), ("Success", 2, True),
        ]
    ]
    outcomes = [task_outcome(event) for event in events]
    assert outcomes == ["non_success", "success", "success"]
    values = [task_metric_values(event).duration_ms for event in events
              if task_outcome(event) == "success"]
    samples = [value for value in values if value is not None]
    assert metric_distribution(samples, 2).valid_count == 2


def test_metric_names_match_exact_fixed_dto_order() -> None:
    from mcp_stdio.plugins.spark.metrics_events import METRIC_NAMES
    assert METRIC_NAMES == (
        "duration_ms", "executor_run_time_ms", "jvm_gc_time_ms", "input_bytes",
        "shuffle_read_bytes", "shuffle_fetch_wait_ms",
    )




def lifecycle(stage: int, attempt: int, submitted: object, completed: object,
              *, name: str = "Completed") -> dict[str, object]:
    return {"Event": f"SparkListenerStage{name}", "Stage Info": {
        "Stage ID": stage, "Stage Attempt ID": attempt,
        "Submission Time": submitted, "Completion Time": completed,
    }}


def measured_task(stage: object, attempt: object, reason: object = "Success",
                  value: object = 0) -> dict[str, object]:
    return {**task(reason), "Stage ID": stage, "Stage Attempt ID": attempt,
            "Task Metrics": {"Input Metrics": {"Bytes Read": value},
                             "Shuffle Read Metrics": {"Remote Bytes Read": value,
                                                       "Local Bytes Read": 0}}}


def stage_request(request: InspectRequest, **filters: object) -> StageMetricsRequest:
    query = query_request(request)
    return StageMetricsRequest.model_validate({
        **request.model_dump(), "expected_sha256": query.expected_sha256, **filters,
    })


@pytest.mark.asyncio
async def test_stage_attempts_counts_totals_and_last_lifecycle(tmp_path: Path) -> None:
    adapter, request = snapshot(tmp_path, [
        lifecycle(17, 0, 1, 9, name="Submitted"),
        lifecycle(17, 0, 10, 30), lifecycle(17, 0, 4, 24),
        measured_task(17, 0, value=0), measured_task(17, 0, value=3),
        measured_task(17, 0, value=None), measured_task(17, 0, "FetchFailed", 100),
        measured_task(17, 0, "UNKNOWN", 100), measured_task(17, 0, None, 100),
        lifecycle(17, 1, 0, 0), measured_task(17, 1, value=7),
        measured_task(18, 0), measured_task(17, None),
        {**measured_task(None, None), "Stage Info": {"Stage ID": 17, "Stage Attempt ID": 0}},
        {**lifecycle(19, 0, 0, 1), "Stage ID": 17, "Stage Attempt ID": 0},
    ])
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = await adapter.stage_metrics(stage_request(request), deadline=time.monotonic() + 10)
    assert result.matched_stage_attempt_count == 4 and result.stages_omitted == 0
    assert result.unassigned_task_end_count == 2
    assert [(s.stage_id, s.stage_attempt_id) for s in result.stages] == [(17, 0), (19, 0),
                                                                                   (17, 1), (18, 0)]
    row = result.stages[0]
    assert (row.submission_time_ms, row.completion_time_ms, row.duration_ms) == (4, 24, 20)
    assert row.submitted_ref is not None and row.submitted_ref.line == 3
    assert row.completed_ref is not None and row.completed_ref.line == 5
    assert row.completed_ref.sha256 == result.snapshot.sha256
    assert (row.task_end_count, row.successful_task_end_count,
            row.non_success_task_end_count, row.unknown_reason_task_end_count) == (6, 3, 2, 1)
    assert row.input_bytes.model_dump() == {"total": 3, "valid_count": 2, "missing_count": 1}
    assert row.shuffle_read_bytes == row.input_bytes
    assert result.stages[2].duration_ms == 0
    assert result.stages[3].submitted_ref is None and result.stages[3].duration_ms is None
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    await adapter.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("start,end", [(3, 2), (None, 4), (False, 4), (0, None), (-1, 0)])
async def test_stage_completed_pair_never_filled_from_submitted(
    tmp_path: Path, start: object, end: object
) -> None:
    adapter, request = snapshot(tmp_path, [lifecycle(0, 0, 1, 8, name="Submitted"),
                                           lifecycle(0, 0, start, end)])
    result = await adapter.stage_metrics(stage_request(request), deadline=time.monotonic() + 10)
    assert result.stages[0].duration_ms is None
    assert result.stages[0].submission_time_ms == metric_integer(start)
    assert result.stages[0].completion_time_ms == metric_integer(end)


@pytest.mark.asyncio
async def test_stage_ranking_before_limit_filter_and_empty(tmp_path: Path) -> None:
    adapter, request = snapshot(tmp_path, [
        lifecycle(2, 1, 0, 5), lifecycle(1, 1, 0, 5), lifecycle(1, 0, 0, 5),
        lifecycle(3, 0, 0, 3, name="Submitted"), measured_task(1, 1, value=9),
        measured_task(True, 0), lifecycle(9, 9, 2, None),
    ])
    result = await adapter.stage_metrics(stage_request(request, limit=1),
                                         deadline=time.monotonic() + 10)
    assert result.matched_stage_attempt_count == 5 and result.stages_omitted == 4
    assert (result.stages[0].stage_id, result.stages[0].stage_attempt_id) == (1, 0)
    selected = await adapter.stage_metrics(stage_request(request, stage_id=1, stage_attempt_id=1),
                                           deadline=time.monotonic() + 10)
    assert selected.unassigned_task_end_count == 1 and selected.matched_stage_attempt_count == 1
    assert selected.stages[0].input_bytes.total == 9
    empty = await adapter.stage_metrics(stage_request(request, stage_id=99, stage_attempt_id=0),
                                        deadline=time.monotonic() + 10)
    assert empty.stages == () and empty.matched_stage_attempt_count == empty.stages_omitted == 0
    assert empty.unassigned_task_end_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["expected_hash", "digest", "tail", "source", "private"])
async def test_stage_scan_rejects_snapshot_corruption(tmp_path: Path, corruption: str) -> None:
    adapter, request = snapshot(tmp_path, [lifecycle(i, 0, 0, i) for i in range(25)])
    metrics_request = stage_request(request, limit=1)
    manifest = Path(request.manifest_path)
    body = json.loads(manifest.read_text())
    path = Path(body["files"][0]["local_path"])
    if corruption == "expected_hash":
        metrics_request = metrics_request.model_copy(update={"expected_sha256": "0" * 64})
    elif corruption == "digest":
        path.write_bytes(path.read_bytes().replace(b'"Stage ID":0', b'"Stage ID":9', 1))
    elif corruption == "tail":
        raw = path.read_bytes() + b'{broken\n'
        path.write_bytes(raw)
        body["files"][0].update(size_bytes=len(raw), event_count=29,
                                  sha256=hashlib.sha256(raw).hexdigest())
        manifest.write_text(json.dumps(body))
        metrics_request = stage_request(request)
    elif corruption == "source":
        body["history_server_url"] = "https://wrong.example"
        manifest.write_text(json.dumps(body))
    else:
        path.chmod(0o644)
    with pytest.raises(SparkGatewayError):
        await adapter.stage_metrics(metrics_request, deadline=time.monotonic() + 10)


@pytest.mark.asyncio
async def test_stage_cancel_timeout_and_shared_close(tmp_path: Path) -> None:
    adapter, request = snapshot(tmp_path, [measured_task(0, 0) for _ in range(1000)])
    metrics_request = stage_request(request)
    with pytest.raises(SparkGatewayError):
        await adapter.stage_metrics(metrics_request, deadline=time.monotonic() - 1)
    worker = asyncio.create_task(adapter.stage_metrics(metrics_request,
                                                       deadline=time.monotonic() + 10))
    await asyncio.sleep(0)
    worker.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker
    workers = [asyncio.create_task(adapter.stage_metrics(metrics_request,
                                                        deadline=time.monotonic() + 10)),
               asyncio.create_task(adapter.inspect(request, deadline=time.monotonic() + 10)),
               asyncio.create_task(adapter.query(query_request(request),
                                                  deadline=time.monotonic() + 10))]
    await asyncio.sleep(0)
    await adapter.close()
    assert all(worker.cancelled() for worker in workers)
    with pytest.raises(asyncio.CancelledError):
        await adapter.stage_metrics(metrics_request, deadline=time.monotonic() + 10)


@pytest.mark.asyncio
async def test_stage_is_offline_with_invalid_lifecycle_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, request = snapshot(tmp_path, [
        {"Event": "SparkListenerStageCompleted", "Stage ID": 4, "Stage Attempt ID": 0},
        lifecycle(True, 0, 0, 1),
        measured_task(4, 0, "FetchFailed", 9),
    ])

    def forbidden_connect(*args: object, **kwargs: object) -> None:
        pytest.fail("offline metrics attempted network access")

    monkeypatch.setattr(socket.socket, "connect", forbidden_connect)
    result = await adapter.stage_metrics(stage_request(request), deadline=time.monotonic() + 10)
    assert result.matched_stage_attempt_count == 1
    stage = result.stages[0]
    assert stage.stage_id == 4 and stage.duration_ms is None
    assert stage.completed_ref is None and stage.task_end_count == 1
    assert stage.successful_task_end_count == 0
    assert stage.input_bytes.model_dump() == {"total": None, "valid_count": 0, "missing_count": 0}
    assert stage.shuffle_read_bytes == stage.input_bytes
    await adapter.close()


def distribution_request(request: InspectRequest, **filters: object):
    from mcp_stdio.plugins.spark.metrics_models import TaskDistributionRequest

    return TaskDistributionRequest.model_validate(
        {
            **stage_request(request).model_dump(),
            "stage_id": 17,
            "stage_attempt_id": 0,
            **filters,
        }
    )


def complete_task(value: int, *, reason: object = "Success") -> dict[str, object]:
    return {
        **measured_task(17, 0, reason, value),
        "Task Info": {
            "Launch Time": 1,
            "Finish Time": value + 1,
            "Task ID": value,
            "Executor ID": "2",
            "Index": 0,
            "Speculative": True,
        },
        "Task Metrics": {
            "Executor Run Time": value,
            "JVM GC Time": value,
            "Input Metrics": {"Bytes Read": value},
            "Shuffle Read Metrics": {
                "Remote Bytes Read": value,
                "Local Bytes Read": 0,
                "Fetch Wait Time": value,
            },
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "order_by",
    [
        "duration_ms",
        "executor_run_time_ms",
        "jvm_gc_time_ms",
        "input_bytes",
        "shuffle_read_bytes",
        "shuffle_fetch_wait_ms",
    ],
)
async def test_distribution_full_samples_ties_and_refs(tmp_path: Path, order_by: str) -> None:
    adapter, request = snapshot(
        tmp_path,
        [
            complete_task(3),
            complete_task(3),
            complete_task(1),
            complete_task(0),
            complete_task(900),
            complete_task(999, reason="FetchFailed"),
            complete_task(999, reason=None),
            measured_task(18, 0, value=999),
            {**complete_task(999), "Stage ID": True},
            {
                **complete_task(999),
                "Stage ID": None,
                "Stage Info": {
                    "Stage ID": 17,
                    "Stage Attempt ID": 0,
                },
            },
        ],
    )
    result = await adapter.task_distribution(
        distribution_request(request, order_by=order_by, limit=2), deadline=time.monotonic() + 10
    )
    assert (
        result.task_end_count,
        result.successful_task_end_count,
        result.non_success_task_end_count,
        result.unknown_reason_task_end_count,
    ) == (7, 5, 1, 1)
    assert result.ranked_task_count == 5 and result.tasks_omitted == 3
    assert [row.ref.line for row in result.top_tasks] == [7, 3]
    for distribution in result.distributions.model_dump().values():
        assert distribution == {
            "valid_count": 5,
            "missing_count": 0,
            "min": 0,
            "p50": 3,
            "p95": 900,
            "max": 900,
        }
    reread = await adapter.query(query_request(request, lines=[7]), deadline=time.monotonic() + 10)
    assert reread.events[0].ref == result.top_tasks[0].ref
    assert reread.events[0].ids.task_id == result.top_tasks[0].task_id == 900
    unlimited = await adapter.task_distribution(
        distribution_request(request, order_by=order_by), deadline=time.monotonic() + 10
    )
    assert unlimited.distributions == result.distributions
    assert [row.ref.line for row in unlimited.top_tasks] == [7, 3, 4, 5, 6]
    await adapter.close()


@pytest.mark.asyncio
async def test_distribution_independent_missing_unknown_ids_and_large_shuffle(
    tmp_path: Path,
) -> None:
    large = complete_task(1)
    large["Task Info"] = {
        "Launch Time": 0,
        "Finish Time": 1,
        "Task ID": True,
        "Executor ID": "invalid id",
    }
    large["Task Metrics"] = {
        "Shuffle Read Metrics": {
            "Remote Bytes Read": 2**63 - 1,
            "Local Bytes Read": 2**63 - 1,
        }
    }
    partial = measured_task(17, 0, value=0)
    partial["Task Info"] = {"Launch Time": 1, "Finish Time": 1}
    adapter, request = snapshot(tmp_path, [large, partial, complete_task(2)])
    result = await adapter.task_distribution(
        distribution_request(request, order_by="shuffle_read_bytes", limit=1),
        deadline=time.monotonic() + 10,
    )
    assert result.top_tasks[0].shuffle_read_bytes == 2**64 - 2
    assert result.top_tasks[0].task_id is None and result.top_tasks[0].executor_id is None
    assert result.distributions.shuffle_read_bytes.valid_count == 3
    assert result.distributions.executor_run_time_ms.missing_count == 2
    assert result.distributions.input_bytes.missing_count == 1
    by_gc = await adapter.task_distribution(
        distribution_request(request, order_by="jvm_gc_time_ms"), deadline=time.monotonic() + 10
    )
    assert by_gc.ranked_task_count == 1 and by_gc.tasks_omitted == 0
    assert by_gc.distributions == result.distributions
    await adapter.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("records", [[], [complete_task(2, reason="FetchFailed")]])
async def test_distribution_empty_success_population(
    tmp_path: Path, records: list[dict[str, object]]
) -> None:
    adapter, request = snapshot(tmp_path, records)
    result = await adapter.task_distribution(
        distribution_request(request), deadline=time.monotonic() + 10
    )
    assert result.task_end_count == len(records)
    assert result.top_tasks == () and result.ranked_task_count == result.tasks_omitted == 0
    assert all(
        value
        == {
            "valid_count": 0,
            "missing_count": 0,
            "min": None,
            "p50": None,
            "p95": None,
            "max": None,
        }
        for value in result.distributions.model_dump().values()
    )
    await adapter.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["expected_hash", "digest", "tail"])
async def test_distribution_validates_full_tail_before_publication(
    tmp_path: Path, corruption: str
) -> None:
    adapter, request = snapshot(tmp_path, [complete_task(900), complete_task(1)])
    metrics_request = distribution_request(request, limit=1)
    manifest = Path(request.manifest_path)
    body = json.loads(manifest.read_text())
    path = Path(body["files"][0]["local_path"])
    if corruption == "expected_hash":
        metrics_request = metrics_request.model_copy(update={"expected_sha256": "0" * 64})
    elif corruption == "digest":
        path.write_bytes(path.read_bytes().replace(b'"Finish Time":2', b'"Finish Time":3'))
    else:
        raw = path.read_bytes() + b"{broken\n"
        path.write_bytes(raw)
        body["files"][0].update(
            size_bytes=len(raw), event_count=6, sha256=hashlib.sha256(raw).hexdigest()
        )
        manifest.write_text(json.dumps(body))
        metrics_request = distribution_request(request, limit=1)
    with pytest.raises(SparkGatewayError):
        await adapter.task_distribution(metrics_request, deadline=time.monotonic() + 10)
    await adapter.close()


@pytest.mark.asyncio
async def test_distribution_cancel_timeout_and_close(tmp_path: Path) -> None:
    adapter, request = snapshot(tmp_path, [complete_task(1) for _ in range(1000)])
    metrics_request = distribution_request(request)
    with pytest.raises(SparkGatewayError):
        await adapter.task_distribution(metrics_request, deadline=time.monotonic() - 1)
    worker = asyncio.create_task(
        adapter.task_distribution(metrics_request, deadline=time.monotonic() + 10)
    )
    await asyncio.sleep(0)
    worker.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker
    worker = asyncio.create_task(
        adapter.task_distribution(metrics_request, deadline=time.monotonic() + 10)
    )
    await asyncio.sleep(0)
    await adapter.close()
    assert worker.cancelled()
    with pytest.raises(asyncio.CancelledError):
        await adapter.task_distribution(metrics_request, deadline=time.monotonic() + 10)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["statistics", "top_projection", "result_validation"])
async def test_distribution_original_deadline_after_computation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    from mcp_stdio.plugins.spark import metrics
    from mcp_stdio.plugins.spark.files import checkpoint as real_checkpoint

    adapter, request = snapshot(tmp_path, [complete_task(1)])
    expired = False
    target = {
        "statistics": "metric_distribution",
        "top_projection": "SparkRankedTask",
        "result_validation": "SparkTaskDistributionResult",
    }[phase]
    original = getattr(metrics, target)

    def expire_after_call(*args: object, **kwargs: object):
        nonlocal expired
        result = original(*args, **kwargs)
        expired = True
        return result

    async def checked(deadline: float) -> None:
        await real_checkpoint(time.monotonic() - 1 if expired else deadline)

    monkeypatch.setattr(metrics, target, expire_after_call)
    monkeypatch.setattr(metrics, "checkpoint", checked)
    with pytest.raises(SparkGatewayError):
        await adapter.task_distribution(
            distribution_request(request), deadline=time.monotonic() + 10
        )
    await adapter.close()


@pytest.mark.asyncio
async def test_distribution_each_metric_selects_its_own_task(tmp_path: Path) -> None:
    from mcp_stdio.plugins.spark.metrics_events import METRIC_NAMES

    records: list[dict[str, object]] = []
    for index, name in enumerate(METRIC_NAMES):
        event = complete_task(1)
        info = {
            "Launch Time": 1,
            "Finish Time": 101 if name == "duration_ms" else 2,
            "Task ID": index,
        }
        metrics = {
            "Executor Run Time": 100 if name == "executor_run_time_ms" else 1,
            "JVM GC Time": 100 if name == "jvm_gc_time_ms" else 1,
            "Input Metrics": {"Bytes Read": 100 if name == "input_bytes" else 1},
            "Shuffle Read Metrics": {
                "Remote Bytes Read": 100 if name == "shuffle_read_bytes" else 1,
                "Local Bytes Read": 0,
                "Fetch Wait Time": 100 if name == "shuffle_fetch_wait_ms" else 1,
            },
        }
        event.update({"Task Info": info, "Task Metrics": metrics})
        records.append(event)
    adapter, request = snapshot(tmp_path, records)
    for index, name in enumerate(METRIC_NAMES):
        result = await adapter.task_distribution(
            distribution_request(request, order_by=name, limit=1), deadline=time.monotonic() + 10
        )
        assert result.top_tasks[0].task_id == index
        assert result.ranked_task_count == 6 and result.tasks_omitted == 5
    await adapter.close()


@pytest.mark.asyncio
async def test_distribution_close_waits_for_post_scan_computation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mcp_stdio.plugins.spark import metrics
    from mcp_stdio.plugins.spark.files import checkpoint as real_checkpoint

    adapter, request = snapshot(tmp_path, [complete_task(1)])
    computing = asyncio.Event()
    released = asyncio.Event()
    original = metrics.metric_distribution
    calculated = False

    def calculate(samples: Sequence[int], successes: int):
        nonlocal calculated
        result = original(samples, successes)
        calculated = True
        return result

    async def pause_after_calculation(deadline: float) -> None:
        if calculated:
            computing.set()
            try:
                await asyncio.Event().wait()
            finally:
                released.set()
        await real_checkpoint(deadline)

    monkeypatch.setattr(metrics, "metric_distribution", calculate)
    monkeypatch.setattr(metrics, "checkpoint", pause_after_calculation)
    worker = asyncio.create_task(
        adapter.task_distribution(distribution_request(request), deadline=time.monotonic() + 10)
    )
    await asyncio.wait_for(computing.wait(), timeout=2)
    await adapter.close()
    assert released.is_set() and worker.cancelled()
