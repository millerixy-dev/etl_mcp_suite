"""Fixed event measurements distinguish missing values from explicit zero."""

import pytest

from mcp_stdio.plugins.spark.metrics_events import metric_integer, task_metric_values


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
