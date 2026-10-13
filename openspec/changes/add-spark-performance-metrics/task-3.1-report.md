# Task 3.1 implementation evidence

Task: the actual OpenSpec task 3.1 MCP service/tools/plugin, operation and stdio/architecture wiring. Parent owns acceptance and the tasks.md checkbox; this report does not gate it.

## Interfaces and runtime

Added SparkMetricsService(gateway: SparkMetricsGateway, request_timeout_seconds: float). `stage_metrics(manifest_path: object, attempt_id: object, expected_sha256: object, **selection: object) -> SparkStageMetricsResult` validates StageMetricsRequest; `task_distribution(...) -> SparkTaskDistributionResult` validates TaskDistributionRequest. Invalid input never calls the port. Each method passes one original monotonic deadline into the gateway and wait_for uses its remaining time; timeout is mapped only after awaited cleanup, while cancellation propagates.

SparkToolAdapter accepts optional metrics_service. Runtime composition supplies the existing SparkInspectionAdapter to both inspection and metrics services, preserving a single directory owner and the existing inspection-close-before-download-close lifecycle. No computation, reader, configuration, persistence or dependency changes.

MCP input signatures:

```python
get_spark_stage_metrics(manifest_path: ManifestPath, attempt_id: AttemptId | None,
                       expected_sha256: Sha256, stage_id: SparkId | None = None,
                       stage_attempt_id: SparkId | None = None, limit: Limit = 20
                       ) -> SparkStageMetricsResult
get_spark_task_distribution(manifest_path: ManifestPath, attempt_id: AttemptId | None,
                           expected_sha256: Sha256, stage_id: SparkId,
                           stage_attempt_id: SparkId, order_by: MetricName = "duration_ms",
                           limit: Limit = 20) -> SparkTaskDistributionResult
```

The exact registered union is fetch_spark_event_log, inspect_spark_event_log, query_spark_events, get_spark_stage_metrics, get_spark_task_distribution. There is no executor-log placeholder. Required nullable attempt and digest, Stage pairing, strict integer bounds, order enum/default and extra-argument rejection are tested.

The whole result is copied through existing redaction, validated against its operation's exact named closed DTO, then scanned for surviving configured secret values. Malformed/wrong DTOs and redaction-invalid application/executor IDs fail closed with UNEXPECTED_RESPONSE. The original internal result is unchanged. New core operation allowlists contain only application_id/attempt_id. Existing inspection error helpers were moved to module scope for reuse without protected-member access.

Architecture guard now rejects metrics/metrics_events direct, relative and from-package alias imports in services. Service imports only the port and domain DTOs.

## RED and GREEN

Before production edits, ran:

`UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/core/test_errors.py tests/unit/plugins/spark/test_service.py tests/unit/plugins/spark/test_tools.py tests/unit/plugins/spark/test_plugin.py tests/contract/test_spark_stdio.py tests/contract/test_architecture.py`

First service-only addition showed 12 expected missing-service failures / 96 passes. Expanded RED showed 26 expected failures / 93 passes: missing SparkMetricsService, absent operation names/two registered tools, and eight metrics infrastructure import forms incorrectly accepted. Separate `... pytest tests/unit/plugins/spark/test_tools.py::test_metrics_schemas_and_strict_inputs` failed with KeyError for missing get_spark_stage_metrics. No production edits preceded those failures.

Initial GREEN with the same scoped paths: 120 passed in 2.97s. Expanded numeric stdio and existing full Spark regression: 542 passed in 18.85s. Added independent fake-port successful named results/deadlines and public wrong-type/secret boundaries; focused service/tools/stdio: 42 passed in 3.00s.

Final fresh verification:

- `UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/core/test_errors.py tests/unit/plugins/spark tests/contract/test_spark_stdio.py tests/contract/test_architecture.py tests/unit/test_registry.py`: **548 passed in 19.20s**.
- `UV_NO_EDITABLE=1 uv run --locked ruff check .`: **All checks passed**.
- `UV_NO_EDITABLE=1 uv run --locked pyright`: **0 errors, 0 warnings, 0 informations**.
- `git diff --check`: exit 0.

An initial Pyright check exposed protected static-helper access and missing test annotations; module-local reuse and explicit annotations fixed those. Ruff exposed one long architecture parametrization line, then formatting fixed it. No metrics algorithm defect or change was needed.

## Actual stdio/offline observations

The driver downloads a synthetic six-event archive (only mocked HTTP), then invokes both new MCP tools in a real stdio process. Stage 17/attempt 0 duration is 900000; successful TaskEnd count is 2; Input total is 300 with valid_count=2/missing_count=0; Shuffle total is 1000. Distribution duration has min/p50=100 and p95/max=900. With limit=1, ranked_task_count=2/tasks_omitted=1; top task is task_id=8 with the returned snapshot digest and physical line 6. Both new tools reject mismatched digest with their own operation names. Old fetch/inspect/query assertions remain.

The restart session forbids HTTP and receives the same readable snapshot/numeric outputs. File bytes and mtimes (excluding ownership lock) are identical before/after every offline call. Process exit is clean, no trailing stdout outside MCP, and synthetic credential markers are absent from public messages/stderr. Basic and cookie fetch paths both retain cross-process cache behavior.

## Review notes and limits

No known task 3.1 gap. Results whose redacted IDs no longer satisfy the closed ID contract intentionally fail closed; they are not silently altered to invented valid IDs. Computation tests continue to cover scanner cancellation, deadline and workers; composition tests prove both ports share the existing single lifecycle owner and its close ordering even on failure.

This is synthetic unit/contract evidence, not a live backend, real private sample or 100 MB performance acceptance. Those final change-wide checks and docs/Skill work remain for tasks 3.2/4.1 and parent review. Unrelated event-log-download spec edits and executor-log artifacts were preserved.
