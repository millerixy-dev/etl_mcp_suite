# Spark inspection MCP wiring Implementation Plan

**Goal:** Implement approved OpenSpec task 3.1, preserving fetch and the single cache owner.
**Architecture:** A gateway-only inspection service validates strict DTOs, applies one deadline, and maps safe operation errors. MCP handlers redact full result values and revalidate closed result schemas. Runtime closes the local inspector before releasing the download gateway lock.
**Tech Stack:** Python 3.10-compatible code, Pydantic, FastMCP, asyncio, pytest; no new dependencies.

## Execution sequence
1. Extend `tests/unit/plugins/spark/test_service.py` with fake inspection gateway tests: invalid combinations rejected before gateway, deadline and cancellation cleanup, operation remapping. Extend tools tests with required nullable attempt, all exact query arguments, strict numeric rejection, metadata redaction and fail-closed structural redaction. Extend actual stdio sessions to inspect/query downloaded evidence and repeat offline. Add architecture probes for inspection infrastructure package aliases. Confirm RED using `uv run --locked pytest tests/unit/plugins/spark/test_service.py tests/unit/plugins/spark/test_tools.py tests/unit/plugins/spark/test_plugin.py tests/contract/test_spark_stdio.py tests/contract/test_architecture.py`.
2. Add two `ToolOperation` enum values and application/attempt identifier allowlists in `src/mcp_stdio/core/errors.py`. Add `SparkInspectionService` in `spark/service.py` consuming `SparkInspectionGateway.inspect/query(request, *, deadline)`; validate `InspectRequest`/`QueryRequest`, wait using the original monotonic deadline, and recreate safe errors under the public operation.
3. Extend `spark/tools.py` with explicit strictly annotated inspect/query handlers, translating the service, `redact_event(result.model_dump(mode='json'), secrets)`, and `type(result).model_validate_json(...)`; guard any remaining configured secret. Register exactly three tools when runtime provides inspection.
4. Compose `SparkInspectionAdapter(settings, secret_values)` in `spark/plugin.py` after download adapter owns cache root; close inspector in `try` and download gateway in `finally`. Retain constructor compatibility for existing direct fetch tests.
5. Reuse the common result/error translation helper and verify fresh affected suite, focused ruff and pyright. Record exact outcomes in task-3.1-report.md; commit only owned source/tests/plan/report. Controller owns the OpenSpec task checkbox.

All behavior follows RED → GREEN → REFACTOR. Every UV command is preceded in its shell by `chflags nohidden .venv/lib/python3.12/site-packages/_editable_impl_hive_cli_mcp_stdio.pth`.
