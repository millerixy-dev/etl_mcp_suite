# Task 2.1 implementation evidence

Implemented `SparkInspectionAdapter(settings: SparkSettings, secret_values: tuple[str, ...] = ())`
with async `inspect(request: InspectRequest, *, deadline: float) -> SparkEventLogInspectionResult`
and async idempotent `close()`. No query implementation, no OpenSpec task checkbox update.

Shared helpers: `task_reason(event) -> tuple[str, bool]` preserves whether UNKNOWN was
explicit; `event_details(event, secrets, max_chars=2048) -> tuple[str, bool]` provides the
fixed labels/Unicode sorted JSON projection, whole-text head/tail bound and repeat
redaction after joining. `direct_ids` remains unchanged.

One reader scan counts the entire verified snapshot. Failure candidates use the required
class priority then physical line; late higher-priority candidates replace earlier entries.
At most 20 bounded failure projections plus 20 bounded fallback projections are retained,
without raw event dictionaries. Worse candidates after the first 20 skip projection.
Snapshot SHA refs are bound only after reader verification succeeds. Active worker tasks
are cancelled and awaited before adapter close returns; this adapter owns no directory lock.

RED: `uv run --locked pytest tests/unit/plugins/spark/test_inspection.py` exited 2 at
collection because `mcp_stdio.plugins.spark.inspection` did not exist. GREEN initially
11 tests passed after implementation, final focused suite 14 passed (0.30 seconds).

Fresh final commands (each uv shell starts with
`chflags nohidden .venv/lib/python3.12/site-packages/_editable_impl_hive_cli_mcp_stdio.pth`):

- `uv run --locked pytest tests/unit/plugins/spark/test_inspection.py`: 14 passed.
- `uv run --locked ruff check src/mcp_stdio/plugins/spark/inspection.py src/mcp_stdio/plugins/spark/inspection_events.py tests/unit/plugins/spark/test_inspection.py`: all checks passed.
- `uv run --locked pyright src/mcp_stdio/plugins/spark/inspection.py src/mcp_stdio/plugins/spark/inspection_events.py tests/unit/plugins/spark/test_inspection.py`: 0 errors, 0 warnings. CLI only printed an available-version notice.

Synthetic real private snapshots cover full-file counts, late failure priority, bounded
samples/category omission, tie ordering, cancellation/Resubmitted and invalid UNKNOWN,
ending fallback/zero candidates/absent end, direct nullable IDs, fixed event projections,
vendor readability, full-text head/tail, configured/pattern redaction and reconstructed
splice secrets, no persistent files, and close cancellation/idempotency.

Integration note for task 3.1: final service result guard must fail closed if configured
credentials or recognized credential patterns occur in raw event type/reason/ID metadata.
Those labels retain their original direct semantics and counts here. Public operation
mapping is also deferred to task 3.1 per controlling-agent scope.

## Task 2.1 review correction: task projection order

The approved TaskStart/TaskEnd projection order is `Task Info`, `Task End Reason`,
`Task Metrics`. Added a focused case with distinct values for each field. RED ran
`chflags nohidden .venv/lib/python3.12/site-packages/_editable_impl_hive_cli_mcp_stdio.pth && uv run --locked pytest tests/unit/plugins/spark/test_inspection.py`:
1 failed, 14 passed; the failure showed `Task End Reason` rendered before `Task Info`.
After changing only the projection tuple, the same focused suite passed 15 tests.
Focused ruff and pyright checks also passed: `chflags nohidden
.venv/lib/python3.12/site-packages/_editable_impl_hive_cli_mcp_stdio.pth && uv run
--locked ruff check src/mcp_stdio/plugins/spark/inspection_events.py
tests/unit/plugins/spark/test_inspection.py` (all checks passed), and `chflags
nohidden .venv/lib/python3.12/site-packages/_editable_impl_hive_cli_mcp_stdio.pth
&& uv run --locked pyright src/mcp_stdio/plugins/spark/inspection_events.py
tests/unit/plugins/spark/test_inspection.py` (0 errors, 0 warnings, 0
informations; available-version notice only).
