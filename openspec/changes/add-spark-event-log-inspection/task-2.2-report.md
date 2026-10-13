# Task 2.2 verification

Implemented `SparkInspectionAdapter.query(QueryRequest, *, deadline)` returning
`SparkEventQueryResult`. Reuses verified reader, direct scalar IDs, task reason
classification and fixed bounded text. Semantic filters precede full-match counts;
line pagination stores at most `limit` projected evidence entries. Reader scans and
verifies EOF/hash even after a page fills. Shared close cancels/awaits inspect/query.
No index, second read, source mutation, network, new lock or schema introduced.
Controller review requested DRY reason aggregation: `_reason_counts(Counter[str])`
now supplies the identical sorted top-32 tuple for inspect and query. Fresh checks
below were rerun after this refactor.

RED: `uv run --locked pytest tests/unit/plugins/spark/test_inspection.py` returned
21 failures, all missing-query AttributeError, with 15 existing tests passing.

Fresh GREEN after formatting/type fixes:

- `uv run --locked pytest tests/unit/plugins/spark/test_inspection.py`: 36 passed (14.35s).
- `uv run --locked ruff check src/mcp_stdio/plugins/spark/inspection.py tests/unit/plugins/spark/test_inspection.py`: all checks passed.
- `uv run --locked pyright src/mcp_stdio/plugins/spark/inspection.py tests/unit/plugins/spark/test_inspection.py`: 0 errors/warnings/informations; informational newer-version notice only.
- `git diff --check -- src/mcp_stdio/plugins/spark/inspection.py tests/unit/plugins/spark/test_inspection.py openspec/changes/add-spark-event-log-inspection/superpowers-plan.md`: exit 0.

Each verification shell repaired the local macOS hidden editable .pth using
`chflags nohidden .venv/lib/python3.12/site-packages/_editable_impl_hive_cli_mcp_stdio.pth`.

Tests cover zero IDs and SQL properties; no inferred job/stage/task or SQL JobEnd
relations; all filter fields and combined filters; event/line OR; unknown/vendor
records and UNKNOWN reasons; empty results; late FetchFailed counts beyond page;
multi-page unique ordered refs and constant counts; past-end terminal empty page;
top-32 reason ties/omissions; same-ref expanded text and 32768 truncation;
incorrect expected hash, digest mismatch and malformed tail after filled page;
query cancellation and shared shutdown. All evidence is synthetic.

Controller retains checkbox gating, broader checks, error operation mapping and
whole-change review. Live backend integration was not run (offline task).
