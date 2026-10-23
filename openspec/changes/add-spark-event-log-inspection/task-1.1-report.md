# Task 1.1 contract implementation report

Scope: strict inspection/query DTOs and read-only gateway only. No scanner, service, MCP wiring, executor implementation or task checkbox mutation.

Commit before: `cd8abb0fed7a6b340320b867139ffcdd58858e57`.
Contract code/plan commit after: `05306a1` (`feat(spark): define offline inspection contracts`).

## Interfaces

`inspection_models.py` exports required-nullable `InspectRequest`, `QueryRequest`, `SparkSnapshot`, `SparkEventRef`, six-field scalar/null `SparkEventIds`, `SparkEventEvidence`, `SparkEventCoverage`, `EventTypeCount`, `TaskReasonCount`, `SparkFailureSignals`, `SparkEventLogInspectionResult` and `SparkEventQueryResult`. Result collections are tuples; JSON serialization produces arrays. Query event_types/lines remain strict JSON lists. Numeric inputs reject bool/string/float coercion, ID bounds are signed-64 nonnegative, line bounds start at one, SHA-256 is 64 lowercase hex. Stage attempt requires stage ID. Expanded details require exactly one requested line and limit=1.

`gateway.py` adds async `SparkInspectionGateway.inspect(request: InspectRequest, *, deadline: float) -> SparkEventLogInspectionResult`, `query(request: QueryRequest, *, deadline: float) -> SparkEventQueryResult`, and `close() -> None`.

## TDD and verification

| Phase | Command | Actual outcome |
| --- | --- | --- |
| RED | `uv run --locked pytest tests/unit/plugins/spark/test_models.py --tb=line` | 95 failures because inspection_models did not exist; 9 old tests passed |
| GREEN | `uv run --locked pytest tests/unit/plugins/spark/test_models.py` | 104 passed |
| REFACTOR fresh test | `uv run --locked pytest tests/unit/plugins/spark/test_models.py` | 104 passed after shared-validator/static-import cleanup |
| Lint | `uv run --locked ruff check src/mcp_stdio/plugins/spark/inspection_models.py src/mcp_stdio/plugins/spark/gateway.py tests/unit/plugins/spark/test_models.py` | All checks passed |
| Types | `uv run --locked pyright src/mcp_stdio/plugins/spark/inspection_models.py src/mcp_stdio/plugins/spark/gateway.py tests/unit/plugins/spark/test_models.py` | 0 errors, 0 warnings |
| Active specifications | `openspec validate --changes --strict` | 16 passed, 0 failed; unrelated informational archive notices |

Environment-only failures occurred before/after valid RED/GREEN because macOS repeatedly hid the editable-install .pth file. `uv sync --locked --reinstall-package hive-cli-mcp-stdio` temporarily repaired imports; the controlling agent identified the hidden flag. Final fresh test was preceded in the same shell invocation by `chflags nohidden .venv/lib/python3.12/site-packages/_editable_impl_hive_cli_mcp_stdio.pth`. No code/config workaround was added and these failures are excluded from functional results.

## Contract wording and ownership

Existing download spec changes were already capability-scoped and left untouched. Updated only the conflicting executor capability spec sentence, executor design registration sentence, and stale inspection proposal sentence to use the exact union of implemented Spark capabilities. User-owned executor artifacts remain unstaged; no executor artifact is included in the focused implementation commit. The controlling agent must review/integrate those sentence changes before marking task 1.1 complete.

No network or integration test executed; no credentials accessed. Only task-specific validation performed here; final full-suite/change review remains with the controlling agent.
