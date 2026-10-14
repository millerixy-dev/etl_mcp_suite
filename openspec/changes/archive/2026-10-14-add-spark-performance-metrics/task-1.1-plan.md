# Spark performance metrics task 1.1 implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development for independent tasks, or superpowers:executing-plans for tightly coupled tasks. This task is executed serially because its DTO and port contracts are shared by later tasks.

**Goal:** Define strict request, result, and gateway contracts for the two offline Spark metrics tools.

**Architecture:** Add one focused `metrics_models.py` that reuses existing Spark snapshot, ref, coverage, IDs, and path validators. Extend the Spark gateway Protocol with two typed async operations. No reader, scan, aggregation, service, or MCP wiring belongs to task 1.1.

**Tech stack:** Python >=3.10, Pydantic v2, pytest, uv, Ruff, Pyright, OpenSpec.

## Global constraints

- Only the files in `/tmp/spark-performance-task-1.1-brief.md` are owned by this task.
- The design and capability spec under `openspec/changes/add-spark-performance-metrics/` define fields and ranges; `tasks.md` remains the only implementation checklist.
- No new dependencies, configuration, network calls, credentials, or persistent artifacts.
- Strict inputs: explicit nullable application attempt, lowercase 64-digit digest, paired nullable Stage identifiers, fixed six metric names, `limit` in [1,20], non-coercive IDs in [0, 2^63−1], and forbidden extra fields.

## Files

- Modify `tests/unit/plugins/spark/test_models.py`: exercise exact request defaults/failures and named result structures; inspect Protocol signatures.
- Create `src/mcp_stdio/plugins/spark/metrics_models.py`: fixed metric and result DTOs.
- Modify `src/mcp_stdio/plugins/spark/gateway.py`: read-only `SparkMetricsGateway` Protocol.
- Create `openspec/changes/add-spark-performance-metrics/task-1.1-report.md`: evidence and self-review.

## Task 1.1: Contracts

The following code sketches were added during execution after the initial plan had already been saved and after the first RED run. They document the actual intended test and interface; they are not claimed as pre-implementation planning evidence. `tasks.md` alone tracks completion.

1. **RED:** Add request, shape, and port tests in `tests/unit/plugins/spark/test_models.py`. The minimal missing-feature probe is:

   ```python
   def test_metrics_requests_are_strict_and_have_fixed_defaults() -> None:
       from mcp_stdio.plugins.spark.metrics_models import StageMetricsRequest

       request = StageMetricsRequest.model_validate(query_values())
       assert request.stage_id is None
       assert request.stage_attempt_id is None
       assert request.limit == 20
   ```

   Then add parametrized rejection for bad digest, bool/string/float IDs and limits, extra keys, unpaired Stage IDs, and unknown `order_by`; exact key-set tests for both result trees; async Protocol signature assertions.

2. **Confirm RED:** Run `UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/plugins/spark/test_models.py`. Expected failure: `metrics_models` missing, with preexisting cases passing.

3. **GREEN:** Implement strict request models in `src/mcp_stdio/plugins/spark/metrics_models.py` and named result models with exactly the design fields. The key validation is:

   ```python
   class MetricsSnapshotRequest(InspectRequest):
       expected_sha256: Sha256

   class StageMetricsRequest(MetricsSnapshotRequest):
       stage_id: SparkId | None = None
       stage_attempt_id: SparkId | None = None
       limit: Annotated[int, Field(ge=1, le=20)] = 20

       @model_validator(mode="after")
       def validate_stage_pair(self) -> StageMetricsRequest:
           if (self.stage_id is None) != (self.stage_attempt_id is None):
               raise ValueError("stage ID and attempt ID must be supplied together")
           return self
   ```

   `TaskDistributionRequest` requires both `SparkId` fields and uses a six-member `Literal` for `order_by`, defaulting to `duration_ms`. `MetricTotal` has `total`, `valid_count`, `missing_count`; `MetricDistribution` has `valid_count`, `missing_count`, `min`, `p50`, `p95`, `max`; `TaskMetricValues` and `TaskMetricDistributions` each name all six design metrics. `SparkStageMetrics`, `SparkRankedTask`, `SparkStageMetricsResult`, and `SparkTaskDistributionResult` have the exact fields shown in design sections 3 and 4. Reuse `SparkSnapshot`, `SparkEventCoverage`, `SparkEventRef`, `SparkModel`, and `validate_attempt_id`.

   Add the gateway contract in `src/mcp_stdio/plugins/spark/gateway.py`:

   ```python
   class SparkMetricsGateway(Protocol):
       async def stage_metrics(
           self, request: StageMetricsRequest, *, deadline: float
       ) -> SparkStageMetricsResult: ...
       async def task_distribution(
           self, request: TaskDistributionRequest, *, deadline: float
       ) -> SparkTaskDistributionResult: ...
       async def close(self) -> None: ...
   ```

4. **Confirm GREEN:** Run the same model test command. Expected: all old and new cases pass.

5. **REFACTOR / checks:** Keep one set of shared validators and named nested DTOs. Re-run model tests, `uv run --locked ruff check src/mcp_stdio/plugins/spark/metrics_models.py src/mcp_stdio/plugins/spark/gateway.py tests/unit/plugins/spark/test_models.py`, `uv run --locked pyright src/mcp_stdio/plugins/spark/metrics_models.py src/mcp_stdio/plugins/spark/gateway.py tests/unit/plugins/spark/test_models.py`, and `openspec validate --changes --strict`; expect exit 0.

6. **Review and commit:** Inspect `git diff` and `git status`, document RED/GREEN results, signatures, concerns, and owned files in the report, then commit only these five owned files. Do not change OpenSpec task checkboxes.

## Self-review before execution

The plan covers 1.1 request validation, exact named result DTOs, and the gateway port. It deliberately excludes metric extraction, verified reader digest behavior, scanning, service registration, and tool exposure assigned to later tasks. Names and result fields are checked against design sections 1, 3, and 4; no placeholder work remains.
