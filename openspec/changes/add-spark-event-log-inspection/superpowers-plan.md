# Spark local inspection implementation micro-plans

> Use superpowers:executing-plans for this shared-contract task. OpenSpec tasks.md remains the only milestone checklist; this plan has no independent completion checkboxes.

**Goal:** Record task-scoped execution details for the minimal local inspection capability; OpenSpec tasks.md owns completion status.

**Architecture:** Reuse Spark models/validators; keep deterministic local scanning in adapters and DTO/operation handling in services. Each section is scoped to one OpenSpec task.

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

## Task 1.2 micro-plan

Files: inspection_reader.py owns descriptor-relative bounded streaming validation;
inspection_events.py owns stateless direct_ids extraction; test_cache.py and fixtures.py
own synthetic private snapshots. No task checkbox edits or new dependencies.

Interface: VerifiedEventLogReader(settings, secret_values=()).read(request, visitor,
*, deadline) returns frozen VerifiedScan(snapshot, spark_version, event_count, coverage)
only after a single complete JSONL traversal. direct_ids(event) returns six nullable scalars.

1. RED: synthetic two-attempt manifest selects null only while unselected file is missing;
   corrupt source/format/hash/count/identity/version/ending/path/tail, missing/symlink,
   size/deadline and numeric extraction parameter tests fail before implementation.
   Run `uv run --locked pytest tests/unit/plugins/spark/test_cache.py`.
2. GREEN: open root O_DIRECTORY|O_NOFOLLOW, walk relative parents using dir_fd,
   require private directories/files and bounded regular manifest; parse closed DTO,
   select exact attempt, open selected JSONL once. Hash raw bounded readline bytes,
   validate JSON/Event/identity/version/end and call visitor each physical record;
   compare all metadata at EOF; close descriptors in finally/cancellation.
   Numeric extraction uses `type(value) is int and 0 <= value <= 2**63-1`;
   JobStart SQL decimal properties use ASCII regex and at most 19 significant digits.
3. REFACTOR/verification: same pytest plus focused ruff and pyright; record actual
   results in task-1.2-report.md and commit only scoped files.

Concrete task 1.2 execution pattern:

```python
@dataclass(frozen=True)
class VerifiedScan:
    snapshot: SparkSnapshot
    spark_version: str
    event_count: int
    coverage: SparkEventCoverage

async def consume(reader: VerifiedEventLogReader, request: InspectRequest,
                  deadline: float) -> VerifiedScan:
    lines: list[int] = []
    return await reader.read(request, lambda line, event: lines.append(line), deadline=deadline)
```

Reader holds only digest, counts, identity/version/ending state. Descriptor-relative
manifest reading duplicates the existing 131072-byte bound because cache._read_manifest
opens by absolute path and cannot safely consume a pinned directory descriptor. Existing
credential_values and MAX_LINE_BYTES are reused. SQL properties accept only ASCII decimal
strings of 1–19 digits, including leading zeros within that bound, and values <=2**63-1.

Task 1.2 RED/GREEN evidence: initial missing-module RED 26 failed/8 passed; overflow
float RED 1 failed/41 passed; canonical ancestor alias RED 1 failed/46 passed.
Fresh final cache verification 47 passed. Focused ruff clean, pyright 0 errors/warnings.
Full details and exact commands are in task-1.2-report.md; parent owns checkbox gate.

## Task 2.1 micro-plan: bounded full-file overview

Task 2.1 review correction: retain the approved `Task Info`, `Task End Reason`,
`Task Metrics` projection order. A focused regression case uses distinct values
for all three labels and verifies their rendered line order.

Files: create `src/mcp_stdio/plugins/spark/inspection.py`, extend
`inspection_events.py`, create `tests/unit/plugins/spark/test_inspection.py`.
No query or public operation mapping; controller alone gates tasks.md.

1. RED: real snapshots use `private_manifest`, replace JSONL and size/hash/count/end
metadata. Assert 25 FetchFailed events plus late JobFailed/Stage failure select
lines `[30,29,3]`, 20 samples and eight omitted, complete counters. Cover invalid
reasons, fallback ending lines, category ties, fixed projection, Unicode,
head/tail, configured/pattern secrets and splice reconstruction, close cancellation.
Run `uv run --locked pytest tests/unit/plugins/spark/test_inspection.py`; expect
missing `inspection` module before implementation.
2. GREEN: `SparkInspectionAdapter.inspect(request, *, deadline)` launches and tracks
an owned reader task; visitor increments Counter types/reasons and signal counts.
Keep at most 20 `(priority,line,bounded evidence)` candidates by insertion/sort/pop and a
separate at-most-20 fallback list; project only new eligible candidates, never retain raw event dicts. `VerifiedEventLogReader.read` returns snapshot,
coverage/count/version; only after verification produce refs. `close()` cancels
and gathers active tasks before return, idempotently.
3. Shared helpers: `task_reason(event)->tuple[str,bool]` validates nonempty bounded
control-free reason; invalid values return `('UNKNOWN',False)`. `event_details`
selects fixed ordered fields, applies `redact_event`, serializes labels and sorted
Unicode JSON, truncates entire text by `text[:limit//2]+text[-(limit-limit//2):]`,
redacts the joined text again and caps any redaction expansion. Counts use raw
reason and direct IDs use `direct_ids` independent of truncated projection.
4. Fresh GREEN verification: focused pytest, focused ruff and pyright. Use
`chflags nohidden .venv/lib/python3.12/site-packages/_editable_impl_hive_cli_mcp_stdio.pth`
in the same shell before uv to repair runtime path discovery. Commit only scoped
implementation/tests/plan/report and report RED/GREEN evidence; no checkbox ledger.

## Task 2.2 — direct query micro-plan (delegated inline execution)

Scope: modify `src/mcp_stdio/plugins/spark/inspection.py` and
`tests/unit/plugins/spark/test_inspection.py`; retain shared helpers and reader.
Produces `query(request: QueryRequest, *, deadline: float) -> SparkEventQueryResult`.
Consumes `reader.read(request, visitor, deadline=deadline) -> VerifiedScan`,
`direct_ids`, `task_reason`, `event_details`. No source/DSL/index or task ledger edits.

1. RED: add parametrized direct zero IDs, stage-attempt, SQL JobStart properties,
list OR / field AND, missing IDs, UNKNOWN/vendor types, complete pagination counts,
rare FetchFailed, reason top-32, bounded ref rereads, corrupt digest/tail and shared
cancellation tests. The concrete test body is committed in `test_inspection.py`.
Run `uv run --locked pytest tests/unit/plugins/spark/test_inspection.py`;
expected missing query AttributeError (observed 21 failures / 15 existing passes).
2. GREEN: implement only the query below. Match all semantic filters before counters;
keep a bounded projection page, count later eligible matches for the cursor, bind
verified digest after EOF. Track both result task types in shared close.

```python
    async def query(self, request: QueryRequest, *, deadline: float) -> SparkEventQueryResult:
        if self._closed:
            raise asyncio.CancelledError
        worker = asyncio.create_task(self._query(request, deadline=deadline))
        self._active.add(worker)
        try:
            return await worker
        finally:
            self._active.discard(worker)

    async def _query(self, request: QueryRequest, *, deadline: float) -> SparkEventQueryResult:
        reasons: Counter[str] = Counter()
        entries: list[SparkEventEvidence] = []
        matched = eligible = 0
        id_filters = {
            field: value
            for field in (
                "execution_id",
                "job_id",
                "stage_id",
                "stage_attempt_id",
                "task_id",
                "executor_id",
            )
            if (value := getattr(request, field)) is not None
        }

        def visit(line: int, event: dict[str, object]) -> None:
            nonlocal matched, eligible
            name = str(event["Event"])
            if request.event_types is not None and name not in request.event_types:
                return
            if request.lines is not None and line not in request.lines:
                return
            ids = direct_ids(event)
            if any(getattr(ids, field) != value for field, value in id_filters.items()):
                return
            reason = task_reason(event)[0] if name == "SparkListenerTaskEnd" else None
            if request.task_end_reason is not None and reason != request.task_end_reason:
                return
            matched += 1
            if reason is not None:
                reasons[reason] += 1
            if line <= request.after_line:
                return
            eligible += 1
            if len(entries) >= request.limit:
                return
            details, truncated = event_details(event, self._secrets, request.max_detail_chars)
            entries.append(
                SparkEventEvidence(
                    ref=SparkEventRef(sha256="0" * 64, line=line),
                    event_type=name,
                    ids=ids,
                    details=details,
                    details_truncated=truncated,
                )
            )

        scan = await self._reader.read(request, visit, deadline=deadline)
        events = tuple(
            entry.model_copy(
                update={"ref": SparkEventRef(sha256=scan.snapshot.sha256, line=entry.ref.line)}
            )
            for entry in entries
        )
        return SparkEventQueryResult(
            snapshot=scan.snapshot,
            matched_count=matched,
            task_end_count=sum(reasons.values()),
            task_end_reasons=_reason_counts(reasons),
            reasons_omitted=max(0, len(reasons) - 32),
            events=events,
            returned_count=len(events),
            next_after_line=events[-1].ref.line if eligible > len(events) and events else None,
            coverage=scan.coverage,
        )

```

3. REFACTOR: preserve direct ID helper; share `_reason_counts(Counter[str])`
for inspect/query top-32 sorting without generic aggregation; use typed Awaitable
cast only at shared gather boundary. Format touched files without unrelated edits.
4. Verify (precede uv calls with `chflags nohidden .venv/lib/python3.12/site-packages/_editable_impl_hive_cli_mcp_stdio.pth`):
`uv run --locked pytest tests/unit/plugins/spark/test_inspection.py`;
`uv run --locked ruff check src/mcp_stdio/plugins/spark/inspection.py tests/unit/plugins/spark/test_inspection.py`;
`uv run --locked pyright src/mcp_stdio/plugins/spark/inspection.py tests/unit/plugins/spark/test_inspection.py`.
Expected 36 passing tests and zero static diagnostics. Record report and scoped commit.
