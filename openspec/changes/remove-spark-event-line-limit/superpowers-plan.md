# Aggregate Event Budget Implementation Plan

> Use superpowers:executing-plans inline: the download and offline reader changes are one tightly coupled task. tasks.md is the sole progress checklist.

**Goal:** Accept >8 MiB events within max_bytes during acquisition and offline reading.

**Architecture:** Keep existing adapters and sequential processing; bound each read by remaining aggregate bytes plus one overflow byte. No new interface or state.

**Tech Stack:** Python >=3.10, standard library, existing pytest/uv tooling.

## Global Constraints

No independent record-size cap or new configuration. Retain separate ZIP/source/output total limits, deadline, redaction, hashes, identity, CRC, private storage and bounded MCP projection. Do not include real event text or credentials in fixtures/reports. Preserve unrelated working-tree changes.

## Task 1.1

Files: `tests/unit/plugins/spark/test_files.py` and `tests/unit/plugins/spark/test_inspection.py`; modify `src/mcp_stdio/plugins/spark/files.py`, `src/mcp_stdio/plugins/spark/inspection_reader.py`, README.md, README.zh-CN.md, docs/architecture/{modules,runtime-flow}.md.

Consumes existing `process_archive(..., max_bytes, deadline)` and shared `VerifiedEventLogReader.read(...)`; produces the same named results, paths and physical-line refs.

1. Add synthetic tests in test_files.py and test_inspection.py. Large acquisition uses the following exact fixture/assertion core; offline test uses snapshot/query_request helpers with the same VendorLargeEvent and asserts count 4, line 3, matching SHA, truncated details <=2048. Small cases exercise exact EOF with/without source newline, total input overflow across two attempts, overflow before parsing invalid tail, redaction growth and selected-file budget boundary. The test source is the executable detail for these cases.

```python
records = events()
records.insert(2, {"Event": "VendorLargeEvent", "payload": "node " * (8 * 1024 * 1024 // 5 + 1)})
data = encode(records)
result = await _process(tmp_path, {APP + "_1": data}, max_bytes=len(data))
assert Path(result[0].local_path).read_bytes() == data
assert result[0].event_count == 4
assert result[0].source_sha256 == hashlib.sha256(data).hexdigest()
```

2. RED: `UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/plugins/spark/test_files.py tests/unit/plugins/spark/test_inspection.py -q`. Expect two >8 MiB tests to fail at old cap, boundary tests to pass.

3. GREEN: remove MAX_LINE_BYTES definition/import and replace download read/checks with:

```python
raw = stream.readline(max_bytes - total_source + 1)
# Existing EOF branch and accounting stay here.
if total_source > max_bytes:
    raise spark_error(ErrorCategory.UPSTREAM_ERROR, explanation="Event log exceeds byte limits.")
# Existing redaction/serialization and output accounting stay here.
if total_output > max_bytes:
    raise spark_error(ErrorCategory.UPSTREAM_ERROR)
```

Reader replacement:

```python
raw = stream.readline(self._settings.max_bytes - size + 1)
# Existing EOF and accounting stay here.
if size > self._settings.max_bytes or count > selected.event_count:
    raise ValueError("event log exceeds limits")
```

4. Run the same focused command; expect all pass. Refactor only unused imports. Add README/architecture sentences explaining aggregate-only record budgets and transient JSON memory growth.
5. Verify `UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/plugins/spark tests/contract/test_spark_stdio.py -q`; independently review this task's diff before marking task 1.1.

## Task 2.1

Use verification-before-completion. Run `UV_NO_EDITABLE=1 uv run --locked pytest -q`, `uv run --locked --no-editable ruff check .`, `uv run --locked --no-editable pyright`, `uv build`, `uv run --locked --no-editable mcp-stdio --help`, `openspec validate --changes --strict`, `openspec validate --specs --strict`. Save exact results in verification-report.md and gate tasks.md. Do not claim live backend download passed without an actual run; existing active MCP process needs restart to pick up source. No automatic archive or unrelated commit.

Self-review: acquisition, offline compatibility and budgets are covered; shared reader already serves metrics. No new configuration/endpoint/schema. Review final code after GREEN; record any correction and verification.
