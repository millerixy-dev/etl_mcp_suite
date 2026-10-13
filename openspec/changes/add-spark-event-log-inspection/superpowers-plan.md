# Spark inspection contracts implementation plan

> Use superpowers:executing-plans for this shared-contract task. OpenSpec tasks.md remains the only milestone checklist; this plan has no independent completion checkboxes.

**Goal:** Implement only OpenSpec task 1.1: strict offline inspection DTOs and read-only gateway signatures, while synchronizing capability-scoped tool-set wording.

**Architecture:** Reuse SparkModel and existing application/attempt/path validators. Keep analysis DTOs in inspection_models.py and the Protocol in gateway.py; add no scanner, I/O, service or tool wiring.

**Tech Stack:** Python >=3.10, uv, Pydantic, pytest; no new dependencies.

## Global constraints

No network, credentials, new configuration, executor-log implementation or tasks.md checkbox edits. Strict numeric/list inputs and immutable tuple result collections. Preserve existing user edits. Canonical source: proposal.md, design.md, tasks.md and specs/spark-event-log-inspection/spec.md in this change.

## Task 1.1 micro-plan

Files: create src/mcp_stdio/plugins/spark/inspection_models.py; modify src/mcp_stdio/plugins/spark/gateway.py and tests/unit/plugins/spark/test_models.py; synchronize only conflicting executor spec/design and stale inspection proposal wording.

Interfaces: InspectRequest(manifest_path: str, attempt_id: str | None), both required; QueryRequest inherits it and adds all exact fields/defaults from design section 2. SparkSnapshot, SparkEventRef, SparkEventIds, SparkEventEvidence, SparkEventCoverage, EventTypeCount, TaskReasonCount, SparkFailureSignals, SparkEventLogInspectionResult and SparkEventQueryResult implement design sections 3–5.

1. RED: Add request tests whose smallest assertions are:

```python
request = InspectRequest(manifest_path="/cache/manifest.json", attempt_id=None)
assert request.attempt_id is None
with pytest.raises(ValidationError):
    InspectRequest(manifest_path="/cache/manifest.json")
with pytest.raises(ValidationError):
    QueryRequest(manifest_path="/cache/manifest.json", attempt_id=None,
                 expected_sha256="a" * 64, job_id=True)
```

Add boundary parametrizations for all request fields, tuple result shape/bounds, six nullable direct IDs, ref digest/line, required nullable fields, extra argument rejection and gateway coroutine signatures. Run `uv run --locked pytest tests/unit/plugins/spark/test_models.py`; expected feature-missing failures before production edits.

2. GREEN: Implement closed DTOs, reusing existing validators with the following concrete request/validation pattern:

```python
class InspectRequest(SparkModel):
    manifest_path: str
    attempt_id: str | None
    _path = field_validator("manifest_path")(validate_local_path)
    _attempt = field_validator("attempt_id")(validate_attempt_id)

class QueryRequest(InspectRequest):
    expected_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    event_types: Annotated[list[str], Field(min_length=1, max_length=16)] | None = None
    execution_id: Annotated[int, Field(ge=0, le=2**63-1)] | None = None
    job_id: Annotated[int, Field(ge=0, le=2**63-1)] | None = None
    stage_id: Annotated[int, Field(ge=0, le=2**63-1)] | None = None
    stage_attempt_id: Annotated[int, Field(ge=0, le=2**63-1)] | None = None
    task_id: Annotated[int, Field(ge=0, le=2**63-1)] | None = None
    executor_id: str | None = None
    task_end_reason: str | None = None
    lines: Annotated[list[Annotated[int, Field(ge=1, le=2**63-1)]], Field(min_length=1, max_length=20)] | None = None
    after_line: Annotated[int, Field(ge=0, le=2**63-1)] = 0
    limit: Annotated[int, Field(ge=1, le=20)] = 20
    max_detail_chars: Annotated[int, Field(ge=1, le=32768)] = 2048
```

A model validator rejects stage_attempt_id without stage_id, duplicate lines, and max_detail_chars>2048 unless lines has exactly one item and limit==1. String validators enforce design lengths/controls and reuse attempt-ID syntax for executor_id. Define result fields exactly as design, counters ge=0, ref line ge=1, IDs bounded/null, SHA-256 lowercase 64 hex, collections tuples bounded 20/32. Spark version nullable when absent. Add:

```python
class SparkInspectionGateway(Protocol):
    async def inspect(self, request: InspectRequest, *, deadline: float) -> SparkEventLogInspectionResult: ...
    async def query(self, request: QueryRequest, *, deadline: float) -> SparkEventQueryResult: ...
    async def close(self) -> None: ...
```

Run the same test command; expected all pass.

3. REFACTOR: Use shared annotated aliases for ID/hash/count/string bounds and existing SparkModel/application/attempt/path validators; retain exact serialized shape. Run `uv run --locked pytest tests/unit/plugins/spark/test_models.py`, `uv run --locked ruff check src/mcp_stdio/plugins/spark/inspection_models.py src/mcp_stdio/plugins/spark/gateway.py tests/unit/plugins/spark/test_models.py`, and `openspec validate --changes --strict`. Review diff and report actual results to controlling agent; no tasks.md completion gate here.

## Execution evidence

- Environment-only initial failure: 104 failures because the editable package import was unavailable. Reinstalled with `uv sync --locked --reinstall-package hive-cli-mcp-stdio`; later recurrence was the local hidden `.pth` flag, cleared with `chflags nohidden .venv/lib/python3.12/site-packages/_editable_impl_hive_cli_mcp_stdio.pth`. These are not counted as RED.
- Valid RED: `uv run --locked pytest tests/unit/plugins/spark/test_models.py --tb=line` returned 95 feature-missing failures and 9 original passes before production edits.
- GREEN: `uv run --locked pytest tests/unit/plugins/spark/test_models.py` returned 104 passed after DTO/port implementation.
- REFACTOR: shared existing validators, local annotated constraints and static module imports; formatted focused files. Fresh same pytest command returned 104 passed after clearing the local hidden flag.
- Focused `uv run --locked ruff check src/mcp_stdio/plugins/spark/inspection_models.py src/mcp_stdio/plugins/spark/gateway.py tests/unit/plugins/spark/test_models.py`: all checks passed.
- Focused `uv run --locked pyright src/mcp_stdio/plugins/spark/inspection_models.py src/mcp_stdio/plugins/spark/gateway.py tests/unit/plugins/spark/test_models.py`: 0 errors, 0 warnings.
- `openspec validate --changes --strict`: 16 passed, 0 failed. Existing informational archive notices remain unrelated.
- No network/integration execution. No task checkbox changed. Cross-change sentence edits remain unstaged to preserve user-owned executor artifacts; controlling agent owns final integration.
