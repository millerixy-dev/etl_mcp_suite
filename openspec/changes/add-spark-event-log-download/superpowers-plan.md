# Spark event log download micro-plans

**Goal:** Implement the approved minimum download tool.
**Architecture:** Spark owns config, models, service/gateway and adapters. OpenSpec tasks.md is the sole progress checklist; these task-scoped notes are subordinate to its specs.
**Tech stack:** Python >=3.10, uv, existing httpx/pydantic/MCP, POSIX stdlib.
**Mode:** Inline executing-plans, chosen in preflight because the tasks share a serial download chain.

## Task 1.1 — Configuration and domain contracts

Files: create src/mcp_stdio/plugins/spark/{__init__,config,models,gateway}.py and tests/unit/plugins/spark/{test_config,test_models}.py; modify src/mcp_stdio/core/errors.py and tests/unit/core/test_errors.py.
Consumes load_config, StrictConfigModel, SecretConfigModel, ToolError.
Produces FetchRequest, SparkSettings, SparkSecrets, SparkEventLogFile/FetchResult and SparkEventLogGateway.lookup/download/close.

1. RED: tests exercise file/env precedence, strict identifiers and exact result fields. Run `uv run --locked pytest tests/unit/plugins/spark/test_config.py tests/unit/plugins/spark/test_models.py tests/unit/core/test_errors.py`. Expected failures: missing Spark module and missing operation.
2. GREEN: strict models and local HTTPS/path/CA validators:
```python
class FetchRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    application_id: str
    attempt_id: str | None = None
    refresh: bool = False
# Shared operation and identifier addition:
FETCH_SPARK_EVENT_LOG = "fetch_spark_event_log"
frozenset({"application_id", "attempt_id"})
```
Full-match ASCII identities and field bounds follow design.md; CA uses ssl.create_default_context(cafile=...) locally and credentials remain SecretStr.
3. VERIFY/REFACTOR: repeat the test command and run `uv run --locked ruff check src/mcp_stdio/plugins/spark tests/unit/plugins/spark tests/unit/core/test_errors.py`; expect all passing with no network.
4. COMMIT: `git add src/mcp_stdio/plugins/spark src/mcp_stdio/core/errors.py tests/unit/plugins/spark tests/unit/core/test_errors.py openspec/changes/add-spark-event-log-download`; `git commit -m "feat(spark): define event log download contracts"`.
Self-review 1.1: only shared contracts; HTTP and publication remain in later OpenSpec tasks.

## Task 2.1 — HTTPS receive adapter

Files: src/mcp_stdio/plugins/spark/http_client.py; tests/unit/plugins/spark/test_http_client.py.
Consumes SparkSettings/SparkSecrets and spark_error. Produces SparkHttpClient.receive(application_id, attempt_id, destination: Path, deadline: float) -> None and close().
1. RED: mock two exact GET paths and status mapping; stream size/timeout/cancel tests. Run `uv run --locked pytest tests/unit/plugins/spark/test_http_client.py --tb=short -q`; expected missing HTTP adapter failures.
2. GREEN: construct lazy client with explicit TLS, never redirects/proxies; receive actual raw chunks under remaining deadline:
```python
suppress_http_transport_logging()
client = httpx.AsyncClient(verify=context, trust_env=False, follow_redirects=False)
await asyncio.wait_for(receive_once(), timeout=deadline - time.monotonic())
# receive_once: status mapping; exclusive 0600 destination; aiter_raw(65536);
# count bytes, reject over max_bytes, inspect bounded prefix, close response.
```
Errors map to fixed domain categories, and finally deletes unsuccessful destination and clears the client's response cookie jar.
3. VERIFY: same test command; `uv run --locked ruff check src/mcp_stdio/plugins/spark/http_client.py tests/unit/plugins/spark/test_http_client.py`; expected pass.
4. COMMIT: `git add src/mcp_stdio/plugins/spark/http_client.py tests/unit/plugins/spark/test_http_client.py openspec/changes/add-spark-event-log-download`; `git commit -m "feat(spark): download bounded authenticated history archives"`.
Self-review 2.1: HTTP has no event interpretation or persistent cache behavior.

## Task 2.2 — ZIP and event validation

Files: src/mcp_stdio/plugins/spark/files.py; tests/unit/plugins/spark/{test_files,fixtures}.py.
Consumes FetchRequest validators, SparkEventLogFile and safe errors. Produces process_archive(archive, directory, application_id, attempt_id, max_bytes, deadline, secret_values=()) -> tuple[SparkEventLogFile,...].
1. RED: synthesize ZipFile members with JSON LogStart/ApplicationStart; unsafe filenames, CRC, identity, JSON and byte-limit variants. Run `uv run --locked pytest tests/unit/plugins/spark/test_files.py -k 'archive or identity or record or limit' --tb=short -q`; expected missing processor failures.
2. GREEN: public ZIP reads, no extractall:
```python
with zipfile.ZipFile(archive) as source:
    for member in source.infolist():
        with source.open(member) as stream:
            raw = stream.readline(MAX_LINE_BYTES + 1)
            event = json.loads(raw)
            source_digest.update(raw)
            # Validate Event, LogStart/version, ApplicationStart/app/attempt.
            # Write one compact UTF-8 record in private staging; never publish here.
```
Use generated output basenames, bound actual source/output totals and line size, consume members to EOF for CRC, reject conflicting/duplicate identities. Cooperative checkpoints check deadline and cancellation.
3. VERIFY: same selected test command and `uv run --locked ruff check src/mcp_stdio/plugins/spark/files.py tests/unit/plugins/spark/test_files.py tests/unit/plugins/spark/fixtures.py`.
4. COMMIT: `git add src/mcp_stdio/plugins/spark/files.py tests/unit/plugins/spark/test_files.py tests/unit/plugins/spark/fixtures.py openspec/changes/add-spark-event-log-download`; `git commit -m "feat(spark): validate history archives and event identities"`.
Self-review 2.2: malformed tails fail; no root-cause or application-state inference.

## Task 2.3 — Fixed credential redaction

Files: src/mcp_stdio/plugins/spark/files.py and tests/unit/plugins/spark/test_files.py.
Consumes validated event dictionaries; produces sanitized JSONL and separate source/output digests.
1. RED: add synthetic nested passwords/tokens/Cookie values, credential URLs and EnvironmentUpdate properties; `uv run --locked pytest tests/unit/plugins/spark/test_files.py -k 'redact or digest' --tb=short -q` must fail on surviving secret text.
2. GREEN: a fixed recursive transformation, before output encoding:
```python
safe_event = redact_event(event, secret_values)
encoded = (json.dumps(safe_event, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")) + "\\n").encode("utf-8")
```
Recognize credential field/assignment and URL userinfo forms, replace known secrets (full Cookie and individual morsels), and retain only the design's static Spark Properties allowlist. Inspect output metadata/serialized records for known values; no migration or rule framework.
3. VERIFY: `uv run --locked pytest tests/unit/plugins/spark/test_files.py` and `uv run --locked ruff check src/mcp_stdio/plugins/spark/files.py tests/unit/plugins/spark/test_files.py`; all pass and digests track actual bytes.
4. COMMIT: `git add src/mcp_stdio/plugins/spark/files.py tests/unit/plugins/spark/test_files.py openspec/changes/add-spark-event-log-download`; `git commit -m "feat(spark): redact credentials from staged event logs"`.
Self-review 2.3: source bytes remain only transient; event structure, order and safe numeric metrics stay intact.

## Task 2.4 — Private directory publication and reuse

Files: src/mcp_stdio/plugins/spark/cache.py; tests/unit/plugins/spark/test_cache.py.
Consumes SparkHttpClient.receive, process_archive and SparkEventLogFetchResult. Produces SparkEventLogAdapter implementing lookup/download/close.
1. RED: test exclusive root lock, restart reuse, source/selector misses, manifest/hash corruption, refresh directories and failed/cancelled staging cleanup. Run `uv run --locked pytest tests/unit/plugins/spark/test_cache.py --tb=short -q`; expected missing adapter failures.
2. GREEN: startup uses fcntl root lock (no network); download serializes under remaining deadline:
```python
staging = Path(tempfile.mkdtemp(prefix=".part-", dir=cache_dir))
try:
    await http.receive(application_id, attempt_id, staging / "archive.zip", deadline=deadline)
    files = await process_archive(staging / "archive.zip", staging, application_id=application_id,
                                  attempt_id=attempt_id, max_bytes=max_bytes, deadline=deadline,
                                  secret_values=secret_values)
    # replace temporary paths with generated final paths; write bounded manifest; delete ZIP
    os.rename(staging, final_directory)
finally:
    # remove only this call's unpublished staging; old directories are immutable
    shutil.rmtree(staging, ignore_errors=True)
```
Lookup reads bounded manifests under exact app/selector, validates source before adoption and re-hashes fixed local files. Never follow symlink roots/files; no GC, dedup, owner marker or extra index.
3. VERIFY: same test command; `uv run --locked ruff check src/mcp_stdio/plugins/spark tests/unit/plugins/spark` and focused pyright.
4. COMMIT: `git add src/mcp_stdio/plugins/spark/cache.py tests/unit/plugins/spark/test_cache.py openspec/changes/add-spark-event-log-download`; `git commit -m "feat(spark): persist and reuse private event log directories"`.
Self-review 2.4: publication is one directory rename; source/request scope and file digests gate reuse.
