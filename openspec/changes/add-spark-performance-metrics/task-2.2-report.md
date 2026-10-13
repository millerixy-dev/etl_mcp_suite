# Task 2.2 execution report

Scope: active Task 2.2 only; controlling agent retains OpenSpec gate ownership. No task checkbox edited. Used writing-plans, inline executing-plans, strict TDD, systematic debugging and verification-before-completion. Parent completed preflight/context selection/strict validation before dispatch.

## Interfaces and changes

```python
async def scan_task_distribution(
    reader: VerifiedEventLogReader, request: TaskDistributionRequest, *, deadline: float
) -> SparkTaskDistributionResult

async def SparkInspectionAdapter.task_distribution(
    self, request: TaskDistributionRequest, *, deadline: float
) -> SparkTaskDistributionResult
```

`metrics.py` reuses metric extraction, classification, nearest-rank statistics and existing direct-ID validators. Only directly matching top-level TaskEnd Stage/attempt IDs contribute. Six unsigned compact arrays include every valid successful metric independently; failed/unknown reasons are counted without contributing. A min-heap keeps at most limit fixed projections with metric descending/line ascending output. Full reader verification and all distributions precede returned top-task construction. Snapshot refs use original sanitized hash and physical line. Original deadline checkpoints surround post-scan statistics/ranking/projection/result validation. `inspection.py` adds this worker to the existing active-set and close lifecycle. Existing Stage/query/inspection code remains unchanged apart from necessary imports/union.

`test_metrics.py` adds all-six ordering, metric-specific distinct winners, ties, limit-independent statistics, late outlier, repeated/speculative sample handling, failure/unknown classification, direct matching rejection, independent missing metrics, valid zero, unsigned Shuffle maximum, unknown IDs retained as null, zero matching/zero successes, ref reread, full-tail/hash conflicts, timeout/cancellation, closed adapter and close waiting during post-scan calculation.

## RED / GREEN evidence

1. Before production edits:
`UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/plugins/spark/test_metrics.py -k distribution`
13 failed / 68 deselected, each because SparkInspectionAdapter.task_distribution was absent. This is the missing feature failure.
2. Initial implementation:
`UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/plugins/spark/test_metrics.py tests/unit/plugins/spark/test_cache.py tests/unit/plugins/spark/test_inspection.py`
164 passed in 14.51s.
3. Deadline refinement RED:
`UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/plugins/spark/test_metrics.py -k original_deadline_after_computation`
1 failed / 2 passed / 82 deselected. Statistics and top projection had checkpoints; synchronous final result validation did not have a following check. Root cause was an immediate return after validation. Minimal fix constructs result, checks original deadline, then returns; no reset/new timeout.
4. Expanded suite including distinct metric winners and post-scan close waiting: 169 passed in 14.62s before final test type annotation. Final fresh rerun recorded below.
5. Scoped Ruff initially found import ordering/long lines. Organized imports and formatted only new task code, restoring existing function formatting to preserve small diffs. Final:
`UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio ruff check src/mcp_stdio/plugins/spark/metrics.py src/mcp_stdio/plugins/spark/inspection.py tests/unit/plugins/spark/test_metrics.py`
All checks passed.
6. Pyright initially found untyped new lists/protected test access, and then the final cancellation helper lacked sample annotations. Added explicit list/Sequence types and removed private assertions; public close/cancellation evidence remains. Final:
`UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pyright`
0 errors, 0 warnings, 0 informations.
7. `git diff --check`: passed.

## Memory and practical limitations

Selected-group valid samples consume six `array("Q")` buffers (8 bytes per valid sample on the tested Darwin runtime), allowing legal sums through 2**64-2. Ranking retains at most limit (1–20) scalar metric/ID projections, never raw dictionaries/events. Exact nearest-rank sorting temporarily creates a Python integer list for one metric at a time: O(selected-group samples), no approximate or truncated distributions. Sorting is synchronous; cancellation/deadline is checked around it, so a single large sort cannot be interrupted midway, but no result publishes after the deadline or cancellation. Arrays/projections are request-local and released with owned work; no persisted aggregate/index/state.

No new dependency, credential, configuration, network call or resource ownership. Synthetic tests require no backend. Live integration was not run; parent retains whole-change full suite/build/strict spec validation/review obligations. Unrelated download specs and executor-log change were left untouched. No known task-scope contract gaps.

Final fresh test command:
`UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/plugins/spark/test_metrics.py tests/unit/plugins/spark/test_cache.py tests/unit/plugins/spark/test_inspection.py`
Result: 169 passed in 14.69s; executed after final annotations. Ruff, Pyright and tests completed sequentially for final verification.

## Controller review follow-up: Stage publication boundary

Controller identified the same original-deadline gap in `scan_stage_metrics`. Systematic-debugging investigation confirmed that Stage row checkpoints precede `SparkStageMetricsResult` validation, but validation was followed immediately by return. The working Task pattern has a checkpoint after result construction. Smallest RED monkeypatches Stage result validation to mark the deadline expired and verifies no successful result can publish afterward.

RED command:
`UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/plugins/spark/test_metrics.py -k stage_original_deadline_after_result_validation`
Result: 1 failed / 86 deselected; expected SparkGatewayError was not raised. This reproduces the concern deterministically without wall-clock sleeps.

Minimal fix: store `SparkStageMetricsResult` in `result`, await `checkpoint(deadline)`, then return it. No ranking, extraction, shape or lifecycle changes.

GREEN command:
`UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/plugins/spark/test_metrics.py tests/unit/plugins/spark/test_cache.py tests/unit/plugins/spark/test_inspection.py`
Result: 170 passed in 14.50s.

Sequential follow-up checks:
`UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio ruff check src/mcp_stdio/plugins/spark/metrics.py src/mcp_stdio/plugins/spark/inspection.py tests/unit/plugins/spark/test_metrics.py`
Result: All checks passed.
`UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pyright`
Result: 0 errors, 0 warnings, 0 informations.
`git diff --check`: passed.

Only metrics.py, test_metrics.py and this report changed in the follow-up. No task checkbox, unrelated change, dependency/config/network or architecture adjustment.
