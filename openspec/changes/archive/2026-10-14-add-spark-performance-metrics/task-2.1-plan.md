# Stage metrics implementation plan

Goal: implement OpenSpec task 2.1 only, with fixed-snapshot full-file Stage-attempt facts.
Architecture: metrics.py aggregates projections via VerifiedEventLogReader; SparkInspectionAdapter owns scans and cancellation. No service/MCP or persistent aggregates.
Tech stack: Python 3.10, existing strict Pydantic contracts, pytest asyncio, uv locked.

Files: src/mcp_stdio/plugins/spark/metrics.py (new aggregate), inspection.py (owned method), inspection_reader.py (SHA guard), tests/unit/plugins/spark/test_metrics.py (Stage tests).

## RED
Append synthetic snapshot tests covering last lifecycle metadata, IDs from the correct event location, success-only totals, null/zero, independent attempts, unassigned all-file counts, pre-limit ranking, filtering, snapshot/path corruption and cancellation.
```python
result = await adapter.stage_metrics(request, deadline=time.monotonic() + 10)
assert result.matched_stage_attempt_count == 3
assert result.unassigned_task_end_count == 1
assert result.stages_omitted == 2
```
Run `UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/plugins/spark/test_metrics.py`; expect missing stage_metrics failures before production changes.

## GREEN
Expose exact aggregate interface:
```python
async def scan_stage_metrics(reader: VerifiedEventLogReader, request: StageMetricsRequest,
                             *, deadline: float) -> SparkStageMetricsResult:
    groups: dict[tuple[int, int], _Stage] = {}
    # visitor counts TaskEnd before rank; lifecycle stores only time pair and last line.
    scan = await reader.read(request, visit, deadline=deadline)
    # Bind retained line refs only after verified EOF; sort duration desc/null-last, IDs asc.
```
Adapter implementation uses existing task collection:
```python
worker = asyncio.create_task(scan_stage_metrics(self._reader, request, deadline=deadline))
self._active.add(worker)
try:
    return await worker
finally:
    self._active.discard(worker)
```
Reader guard:
```python
if isinstance(request, (QueryRequest, MetricsSnapshotRequest)):
    if request.expected_sha256 != selected.sha256:
        raise ValueError("snapshot conflict")
```
No event arrays retained; per-group dataclass holds counters, sums, timestamps and source line integers only. Explicit valid UNKNOWN reason is non_success. Timestamp pair comes from the final Completed even if incomplete, otherwise final Submitted.

## REFACTOR and verify
Keep aggregates limited to counters/sums/projections; use pure metric helpers, retain no raw event dictionaries. Run sequentially:
`UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/plugins/spark/test_metrics.py tests/unit/plugins/spark/test_inspection.py tests/unit/plugins/spark/test_cache.py`
`uv run --locked ruff check src/mcp_stdio/plugins/spark/metrics.py src/mcp_stdio/plugins/spark/inspection.py src/mcp_stdio/plugins/spark/inspection_reader.py tests/unit/plugins/spark/test_metrics.py`
`uv run --locked pyright src/mcp_stdio/plugins/spark/metrics.py src/mcp_stdio/plugins/spark/inspection.py src/mcp_stdio/plugins/spark/inspection_reader.py tests/unit/plugins/spark/test_metrics.py`
Report exact results and final interfaces in task-2.1-report.md. Commit only owned files. Parent reviews and performs fresh task gate; tasks.md untouched.

Self-review: design sections 1/2/3/5 and Stage capability scenarios covered. Method/type names match task 1 DTOs; no cross-event timestamp fill or query-semantic change. No competing checkboxes, dependencies, configuration, network or credentials.
