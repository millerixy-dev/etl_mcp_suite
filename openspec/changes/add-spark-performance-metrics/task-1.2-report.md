# Task 1.2 report

Implemented only pure helpers in metrics_events.py and tests; no scan, reader, gateway, service, adapter, config or dependency changes. tasks.md remains untouched for the controlling agent's fresh gate.

## Exact internal interfaces for Stage/distribution tasks

```python
METRIC_NAMES: tuple[MetricName, ...] = (
    "duration_ms", "executor_run_time_ms", "jvm_gc_time_ms",
    "input_bytes", "shuffle_read_bytes", "shuffle_fetch_wait_ms",
)
def metric_integer(value: object) -> int | None: ...
def task_metric_values(event: dict[str, object]) -> TaskMetricValues: ...
def task_outcome(event: dict[str, object]) -> Literal["success", "non_success", "unknown"]: ...
def metric_distribution(values: Sequence[int], successful_count: int) -> MetricDistribution: ...
```

metric_integer accepts strict raw integers 0..2**63-1 only, useful for Stage timestamps too. task_metric_values does not filter reasons; callers must count all TaskEnd classifications then use only success values. Each TaskEnd is its own attempt; helpers perform no identity deduplication. task_outcome delegates validity to inspection_events.task_reason, so explicit valid UNKNOWN is non_success, while invalid/missing is unknown. metric_distribution expects already validated samples and successful_count >= len(values); callers must not revalidate summed Shuffle values against the raw signed64 bound. It sorts a copy, does not mutate or retain the input, preserves arbitrary Python integer sums, and uses integer ceil arithmetic for fixed p50/p95.

## RED/GREEN evidence

All Python commands used uv locked. Reinstalling commands were sequential to avoid shared package races.

1. Initial extraction test command:
`UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/plugins/spark/test_metrics.py`
Result: exit 2, collection error `ModuleNotFoundError: No module named 'mcp_stdio.plugins.spark.metrics_events'`. This established missing module only; it was followed by behavior RED with minimal None-returning stubs.

2. Same command after stubs: exit 1, `8 failed, 27 passed in 0.12s`. Expected failures included `assert None == 0`, six extracted values null instead of concrete values, missing Task Metrics losing valid duration, and absent large Shuffle sum.

3. Same command after extraction implementation: exit 0, `35 passed in 0.09s`.

4. Same command after classification/distribution tests: exit 1, `18 failed, 36 passed in 0.17s`, missing helper imports. Followed with minimal unknown/empty-distribution stubs to verify behavioral RED.

5. `UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/plugins/spark/test_metrics.py --tb=short`
Result: exit 1, `9 failed, 45 passed in 0.12s`. Expected unknown vs success/non_success and empty vs populated distribution assertion failures, including retry/speculative attempts.

6. Final command:
`UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/plugins/spark/test_metrics.py`
Result: exit 0, `54 passed in 0.12s`.

7. `uv run --locked ruff check src/mcp_stdio/plugins/spark/metrics_events.py tests/unit/plugins/spark/test_metrics.py`
Result: exit 0, `All checks passed!`.

8. `uv run --locked pyright src/mcp_stdio/plugins/spark/metrics_events.py tests/unit/plugins/spark/test_metrics.py`
Result: exit 0, `0 errors, 0 warnings, 0 informations`.

## Self-review and limits

Compared design section 2 and sample/distribution capability scenarios against tests: zero/absent, invalid bool/string/float/negative/overflow values, malformed/missing objects, invalid timestamps, both Shuffle components, large component sum, missing metrics with usable duration, valid/invalid reason distinction, retries/speculation without deduplication, empty/single/double/20-value nearest-rank, unmodified inputs and exact fixed name order are covered. No arbitrary event data appears in DTOs. Existing task_reason is reused rather than duplicated. No unresolved requirement concern.

Scope limitation: these are pure local helpers, not TaskEnd scanners; Stage/distribution adapters must enforce event selection and successful sample count invariants. Full suite, architecture/runtime integration and strict OpenSpec validation remain the parent's whole-change gate. No live integration was run or claimed. Unrelated download/executor artifacts were preserved.

## Controller gate

Fresh controller command `UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/plugins/spark/test_metrics.py` passed: 54 tests in 0.12s. Independent task review: spec compliant, quality Approved, no findings. TaskEnd selection, success-only scan counts, full snapshot/digest checking and lifecycle remain later-task gates.
