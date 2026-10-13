# Task 2.1 Stage metrics report

Implemented Stage metrics only. OpenSpec tasks.md is unchanged; controller review/fresh verification must gate it. No service/core/MCP, distribution method, network, credentials, configuration, dependency or state changes.

## Files and interfaces

- `src/mcp_stdio/plugins/spark/metrics.py`: async `scan_stage_metrics(reader: VerifiedEventLogReader, request: StageMetricsRequest, *, deadline: float) -> SparkStageMetricsResult`. Aggregates retain only counters, sums, strict timestamp pairs and last Submitted/Completed physical line numbers per Stage attempt. Successful samples use existing task helpers; refs bind only after verified EOF. Lifecycle IDs are Stage Info only; TaskEnd IDs are top-level only. Completed metadata overrides Submitted without cross-event filling. Sorting is duration descending/null-last then IDs ascending; population counts precede limit. Invalid/unassigned TaskEnd count is whole-file even under Stage filtering.
- `src/mcp_stdio/plugins/spark/inspection.py`: async `SparkInspectionAdapter.stage_metrics(request: StageMetricsRequest, *, deadline: float) -> SparkStageMetricsResult`, uses existing owned tasks and close/cancel lifecycle.
- `src/mcp_stdio/plugins/spark/inspection_reader.py`: expected SHA guard now covers QueryRequest and MetricsSnapshotRequest; existing query selection behavior unchanged. Thus future TaskDistributionRequest inherits fixed-snapshot enforcement too.
- `tests/unit/plugins/spark/test_metrics.py`: existing 54 pure tests preserved; 14 Stage cases added (68 total), including direct ownership, attempts, invalid lifecycle identity, last metadata/ref, zero/reversed/missing timestamps, success-only valid/missing totals, explicit UNKNOWN reason, pre-limit tie ordering, filter/empty, immutable evidence, network-connect prohibition, digest/tail/source/private corruption, timeout/cancel/shared shutdown.
- Active-change task-2.1-plan.md and this report.

## RED/GREEN evidence

All uv package reinstalls/checks ran sequentially.

1. RED: `UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/plugins/spark/test_metrics.py --tb=short` -> exit 1, **13 failed, 54 passed in 0.28s**, new cases fail because existing SparkInspectionAdapter has no stage_metrics method. Production files unchanged before this run.
2. First GREEN attempt, same command -> exit 1, **1 failed, 66 passed in 0.25s**. Digest corruption fixture did not mutate its compact JSON because it searched a spaced token. Systematic investigation confirmed `fixtures.encode` uses separators=(",", ":"); corrected replacement to compact token, no production fix.
3. Initial Ruff found one overlong production line plus expected synchronous fixture Path calls; broke line and reused inspector's documented ASYNC240 exemption for small synthetic fixtures. Imports reordered with Ruff. Pyright already returned zero errors.
4. Regression verification: `UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/plugins/spark/test_metrics.py tests/unit/plugins/spark/test_inspection.py tests/unit/plugins/spark/test_cache.py` -> exit 0, **150 passed in 14.38s**.
5. After explicit offline/invalid-lifecycle/no-success verification case: same regression command -> exit 0, **151 passed in 14.47s**.
6. `uv run --locked ruff check src/mcp_stdio/plugins/spark/metrics.py src/mcp_stdio/plugins/spark/inspection.py src/mcp_stdio/plugins/spark/inspection_reader.py tests/unit/plugins/spark/test_metrics.py` -> exit 0, **All checks passed!**
7. `uv run --locked pyright src/mcp_stdio/plugins/spark/metrics.py src/mcp_stdio/plugins/spark/inspection.py src/mcp_stdio/plugins/spark/inspection_reader.py tests/unit/plugins/spark/test_metrics.py` -> exit 0, **0 errors, 0 warnings, 0 informations**.
8. `openspec validate add-spark-performance-metrics --strict` -> exit 0, **Change is valid**. `git diff --check` -> exit 0.

## Self-review and limits

Compared implementation to design 1/2/3/5 and Stage capability requirements. No full event arrays or metadata bodies retained; no aggregate persistence, network or partial success. MetricTotal null/zero and independent valid/missing counts match success samples. Reader digest enforcement and private evidence checks are reused. Deadline checkpoints cover scan plus before/after ranking and each returned projection. Ranking uses temporary group-reference sorting (O(groups log groups)); retained per-group aggregates are O(groups), without per-task arrays.

Task 2.2 must extend metrics.py and the same adapter owned-task type union with task_distribution, not create a second lifecycle. Full suite/build/MCP contracts and whole-change strict validation remain controller final gates; no live integration run or claimed. Unrelated download/executor artifacts preserved.
