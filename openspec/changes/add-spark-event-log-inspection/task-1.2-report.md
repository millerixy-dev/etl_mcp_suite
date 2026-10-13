# Task 1.2 execution report

Implemented only local snapshot validation and direct identifier extraction. No OpenSpec
checkbox changed. No network, runtime lock, production writes, or service/tool wiring.

## Interfaces

- `VerifiedEventLogReader(settings: SparkSettings, secret_values: tuple[str, ...] = ())`
- `async read(request: InspectRequest, visitor: Callable[[int, dict[str, object]], None], *, deadline: float) -> VerifiedScan`
- Frozen `VerifiedScan(snapshot: SparkSnapshot, spark_version: str, event_count: int, coverage: SparkEventCoverage)`
- `inspection_events.direct_ids(event: dict[str, object]) -> SparkEventIds`

Visitor runs during one bounded streaming pass. Only after EOF hash/count/size/identity,
version/ending checks does read return metadata. Caller must discard visitor state upon
failure. Exactly the selected attempt is scanned; null means actual null. QueryRequest
uses expected_sha256, never source_sha256. No reader close method: lexical ExitStack
owns descriptors and closes on success, exception, cancellation. Future adapter owns
worker tracking and shutdown.

Configured root ancestor aliases are normalized consistently with acquisition, while
root and all descendants use no-follow directory/file descriptors. Evidence must be
owned by the effective user and inaccessible to group/others. No parent path symlinks
below root are accepted. Manifest uses 131072-byte bound; selected file uses configured
max_bytes and existing MAX_LINE_BYTES. Nonfinite constants and exponent overflow fail.

`direct_ids` does not infer relationships. SQL decimal property accepts bounded ASCII
1–19 digits (leading zeros allowed within bound), integer range 0..2**63-1. Invalid
booleans/types/values become null.

## RED

Prefix local test commands with:
`chflags nohidden .venv/lib/python3.12/site-packages/_editable_impl_hive_cli_mcp_stdio.pth`
(the macOS editable-install environment workaround; no code/environment mutation added).

- `uv run --locked pytest tests/unit/plugins/spark/test_cache.py --tb=line`
  Initial new reader/extractor tests: 26 feature-missing failures, 8 existing passes.
- Same command after malformed-tail tests: 1 meaningful failure for `1e400`, 41 passes.
  Correct matching manifest hash/count/size ensured this exercised JSON validation.
- Same command after configured ancestor-alias regression: 1 meaningful failure, 46 passes.

## Fresh GREEN / REFACTOR verification

- `uv run --locked pytest tests/unit/plugins/spark/test_cache.py`: 47 passed.
- `uv run --locked ruff check src/mcp_stdio/plugins/spark/inspection_reader.py src/mcp_stdio/plugins/spark/inspection_events.py tests/unit/plugins/spark/test_cache.py tests/unit/plugins/spark/fixtures.py`: all checks passed.
- `uv run --locked pyright src/mcp_stdio/plugins/spark/inspection_reader.py src/mcp_stdio/plugins/spark/inspection_events.py tests/unit/plugins/spark/test_cache.py tests/unit/plugins/spark/fixtures.py`: 0 errors, 0 warnings. Tool printed informational newer-version notice.

Coverage includes selected-only multi-attempt/null, no latest fallback, source/schema/path,
hash/count/application/attempt/version/ending mismatches, malformed tail/nonobjects/Event,
missing/symlink/parent-symlink, private modes, size/deadline, query digest, one JSONL open,
and descriptor closure on success/cancel. All fixtures are synthetic.

Integration/network tests not run; parent controls broader suite and strict OpenSpec gates.
