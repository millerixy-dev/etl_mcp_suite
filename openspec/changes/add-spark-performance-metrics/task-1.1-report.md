# Task 1.1 implementation report

## Status and scope

Implemented the strict Pydantic request/result contracts and read-only async gateway port for the two offline performance tools. No scanning, aggregation, reader changes, service registration, network call, configuration, or task checkbox change was made. Shared contracts were implemented serially before later tasks.

Owned changes: `src/mcp_stdio/plugins/spark/metrics_models.py` (new), `src/mcp_stdio/plugins/spark/gateway.py`, `tests/unit/plugins/spark/test_models.py`, and this report and `task-1.1-plan.md` within the change.

## RED / GREEN evidence

- Initial RED command: `UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/plugins/spark/test_models.py` → exit 1, **40 failed / 104 passed**. New tests failed with `ModuleNotFoundError: No module named 'mcp_stdio.plugins.spark.metrics_models'`; existing tests passed. This was before production DTO/port code.
- First GREEN attempt: same command with `-q` → exit 1, **1 failed / 143 passed**. The shape test passed a list to a strict tuple field; corrected the test to use tuples, consistent with existing immutable result models.
- Follow-up RED for existing executor-ID safety: same command with `-q` → exit 1, **1 failed / 143 passed**, because `SparkRankedTask` accepted `../3`. Reused `validate_attempt_id` on its `executor_id` field.
- Final GREEN command: same command with `-q` → exit 0, **144 passed in 0.17s**.
- Ruff: `uv run --locked ruff check src/mcp_stdio/plugins/spark/metrics_models.py src/mcp_stdio/plugins/spark/gateway.py tests/unit/plugins/spark/test_models.py` → exit 0, `All checks passed!`.
- Pyright: `uv run --locked pyright src/mcp_stdio/plugins/spark/metrics_models.py src/mcp_stdio/plugins/spark/gateway.py tests/unit/plugins/spark/test_models.py` → exit 0, `0 errors, 0 warnings, 0 informations`.
- OpenSpec: `openspec validate --changes --strict` → exit 0, **17 passed / 0 failed**. Existing archive advisory INFO messages appeared for unrelated changes.

One test collection attempt failed transiently because pytest, Ruff, and Pyright were launched simultaneously through `uv run` while `--reinstall-package` replaced the shared local package. These checks were rerun sequentially; final results above are from the stable environment.

## Final interfaces

`MetricsSnapshotRequest(InspectRequest)` adds required `expected_sha256: Sha256`; `StageMetricsRequest` adds optional paired `stage_id: SparkId | None`, `stage_attempt_id: SparkId | None`, and `limit: 1..20 = 20`; `TaskDistributionRequest` requires both Stage IDs and adds `order_by: MetricName = "duration_ms"`, `limit: 1..20 = 20`. `MetricName` is exactly the six design metric names. All requests inherit strict, frozen, extra-forbidden validation and explicit nullable application `attempt_id` from `InspectRequest`.

`MetricTotal(total: Count | None, valid_count: Count, missing_count: Count)`; `MetricDistribution(valid_count: Count, missing_count: Count, min/p50/p95/max: Count | None)`; `TaskMetricValues` has six nullable numeric metrics and `TaskMetricDistributions` has six named `MetricDistribution` fields. `SparkStageMetrics`, `SparkRankedTask`, `SparkStageMetricsResult`, and `SparkTaskDistributionResult` expose exactly the design's named fields, reusing `SparkSnapshot`, `SparkEventCoverage`, and `SparkEventRef`. Stage and top-task collections are bounded tuples of at most 20 entries. Ranked task IDs and executor IDs reuse existing direct-ID validation.

`SparkMetricsGateway` defines async `stage_metrics(request: StageMetricsRequest, *, deadline: float) -> SparkStageMetricsResult`, async `task_distribution(request: TaskDistributionRequest, *, deadline: float) -> SparkTaskDistributionResult`, and async `close() -> None`.

## Self-review and handoff concerns

Checked exact field sets against design sections 3 and 4, request ranges and coercion rules against sections 1/3/4, and port signatures against the existing Spark gateway style. The DTOs intentionally do not calculate counts or enforce cross-field aggregate arithmetic; tasks 1.2 and 2.x own those behaviors. In task 1.2, a valid explicit reason with value `UNKNOWN` belongs in **non_success_task_end_count**; an absent or invalid reason belongs in **unknown_reason_task_end_count**. Use the existing `task_reason` validity flag to distinguish these cases. When task 2.x wires `MetricsSnapshotRequest` to `VerifiedEventLogReader`, it must enforce `expected_sha256` against the sanitized JSONL digest before returning aggregates; task 1.1 only validates the digest syntax.

No known remaining contract issue in task 1.1. The report's first RED and final GREEN commands were run using a regular package reinstall because the macOS environment can otherwise mask source changes through editable installation state.
