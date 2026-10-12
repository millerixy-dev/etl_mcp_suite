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

## Task 3.1 — Application service

Files: src/mcp_stdio/plugins/spark/service.py; tests/unit/plugins/spark/test_service.py.
Consumes gateway lookup/download and FetchRequest. Produces SparkEventLogService.fetch(application_id, attempt_id=None, refresh=False) -> SparkEventLogFetchResult.
1. RED: fake gateway tests input rejection, hit/miss, refresh bypass, unchanged download time and deadline/error propagation. Run `uv run --locked pytest tests/unit/plugins/spark/test_service.py --tb=short -q`; expected missing service.
2. GREEN:
```python
async def _fetch(self, request: FetchRequest, deadline: float) -> SparkEventLogFetchResult:
    if not request.refresh:
        hit = await self._gateway.lookup(request.application_id, request.attempt_id,
                                         deadline=deadline)
        if hit is not None:
            return hit
    return await self._gateway.download(request.application_id, request.attempt_id,
                                        deadline=deadline)
```
Public fetch strictly validates first and wraps _fetch in asyncio.wait_for with the same total deadline; timeout and invalid inputs use safe domain errors.
3. VERIFY: repeat test command; focused ruff/pyright. Service imports no HTTP, filesystem adapter or MCP.
4. COMMIT: `git add src/mcp_stdio/plugins/spark/service.py tests/unit/plugins/spark/test_service.py openspec/changes/add-spark-event-log-download`; `git commit -m "feat(spark): coordinate cached and refreshed log acquisition"`.
Self-review 3.1: request orchestration uses the fixed port without backend imports.

## Task 3.2 — MCP registration and explicit plugin wiring

Files: plugins/spark/{tools,plugin}.py; contracts/plugin.py; registry.py; bootstrap.py; core/server.py; tests/unit/plugins/spark/{test_tools,test_plugin}.py; tests/unit/test_registry.py; tests/contract/{import_rules,test_architecture}.py.
Consumes Spark service/gateway and PluginRuntime/ToolRegistrar. Produces one fetch_spark_event_log tool and explicit spark loader.
1. RED: exact tool/argument schema, raw unknown/string-bool rejection, safe error/secret outputs, local startup/close and new registry/architecture contracts. Run `uv run --locked pytest tests/unit/plugins/spark/test_tools.py tests/unit/plugins/spark/test_plugin.py tests/unit/test_registry.py tests/unit/core/test_bootstrap.py tests/contract/test_architecture.py --tb=short -q`; expected missing adapter/registry and source-boundary failures.
2. GREEN: composition follows existing plugins:
```python
gateway = SparkEventLogAdapter(settings=loaded.settings, secrets=loaded.secrets)
service = SparkEventLogService(gateway=gateway,
                              request_timeout_seconds=loaded.settings.request_timeout_seconds)
tools = SparkToolAdapter(service=service, secret_values=redaction_values)
registrar.add_tool(tools.fetch_spark_event_log, name="fetch_spark_event_log")
```
Use strict Annotated input fields; shared stdio models validate raw arguments with extra=forbid before SDK preprocessing and map failures to a fixed safe ToolError. Only registry imports Spark from shared code; service-to-files/cache imports are prohibited by AST tests.
3. VERIFY: repeat the command, focused ruff/pyright and core server tests; no startup network.
4. COMMIT: `git add src/mcp_stdio tests/unit/plugins/spark tests/unit/test_registry.py tests/contract/import_rules.py tests/contract/test_architecture.py openspec/changes/add-spark-event-log-download`; `git commit -m "feat(spark): expose the download tool through the stdio plugin"`.
Self-review 3.2: input safety gap updated in OpenSpec before core changes; one fixed plugin surface only.

## Task 3.3 — Stdio chain, shutdown and opt-in integration

Files: tests/contract/test_spark_stdio.py; tests/integration/{test_spark_server,test_opt_in}.py; tests/unit/plugins/spark/test_cache.py; plugins/spark/cache.py.
Consumes full runtime. Produces verified download/restart-hit/error stdio calls, active-download shutdown cleanup and an environment-gated live test.
1. RED: subprocess mock transport handshake/call/EOF tests; missing opt-in prerequisites must skip before constructing a gateway; active adapter.close must cancel and await owned acquisitions. Run `PYTHONPATH=src uv run --locked pytest tests/contract/test_spark_stdio.py tests/contract/test_subprocess_smoke.py tests/integration/test_opt_in.py tests/unit/plugins/spark/test_cache.py --tb=short -q`; expected missing live entry and active shutdown cleanup failures.
2. GREEN: track owned worker tasks without background persistence:
```python
worker = asyncio.create_task(self._download(application_id, attempt_id, deadline))
self._acquisitions.add(worker)
try:
    return await asyncio.wait_for(worker, timeout=remaining)
finally:
    self._acquisitions.discard(worker)
# close marks closed; cancels/gathers the owned workers before closing client/root lock.
```
Live test requires explicit gate, application ID and SPARK deployment URL/cache/Cookie; it loads config only after prerequisites and always closes. No network in default suite.
3. VERIFY: same command; focused lint/type checks. Stdio asserts protocol-only stdout, sanitized error/results, no raw ZIP and released root lock.
4. COMMIT: `git add src/mcp_stdio/plugins/spark/cache.py tests/contract/test_spark_stdio.py tests/unit/plugins/spark/test_cache.py tests/integration openspec/changes/add-spark-event-log-download`; `git commit -m "test(spark): verify stdio acquisition and shutdown lifecycle"`.
Self-review 3.3: transport/file matrices stay in unit tests; live download is never enabled implicitly.

## Task 4.1 — Usage, configuration and architecture documentation

Files: README.md, README.zh-CN.md, docs/examples/spark.{yaml,json}, docs/architecture/{runtime-flow,modules}.md, AGENTS.md; tests/unit/plugins/spark/test_config.py.
Consumes implemented settings/tool/result contracts. Produces equivalent executable examples and coherent four-plugin documentation.
1. RED: add example-loading test with cache/env overrides and synthetic Cookie, run `PYTHONPATH=src uv run --locked pytest tests/unit/plugins/spark/test_config.py --tb=short -q`; expected missing Spark examples.
2. EDIT: add five-setting table, file/env-only/host launch, fetch/refresh contract, output example, provenance/redaction/retention and opt-in instructions. Update process topology and Spark ownership/modules; correct stale DolphinScheduler delivery descriptions while touching the topology.
3. VERIFY: run the configuration test and strict change validation; manually compare documented fields, defaults, paths, transport and cleanup to design/specs. No code behavior is changed in this task.
4. COMMIT: `git add README.md README.zh-CN.md docs/examples/spark.yaml docs/examples/spark.json docs/architecture AGENTS.md tests/unit/plugins/spark/test_config.py openspec/changes/add-spark-event-log-download`; `git commit -m "docs(spark): document event log acquisition and local evidence"`.
Self-review 4.1: examples use placeholders, optional CA and environment secret names; no live fixture or credential values.

## Task 4.2 — Review corrections and full verification

Files: core/server.py; plugins/spark/{http_client,files}.py; corresponding regression tests; this change's verification.md.
Consumes independent code review against d2d80c1..edf0eac and all approved requirements.
1. RED: separate regressions for literal nullable attempt "null", ambient SSL_CERT_FILE/SSL_CERT_DIR isolation and multi-value unknown Cookie strings. Run the individual selected pytest commands before each fix; expected scope change, implicit CA override and retained second cookie failures.
2. GREEN (one finding at a time):
```python
class _RawArguments(FuncMetadata):
    def pre_parse_json(self, data: dict[str, Any]) -> dict[str, Any]:
        return data
# Install this metadata on the registered SDK tool, preserving its output metadata.
verify = ssl.create_default_context(cafile=ca_path) if ca_path else True
# HTTPX verify=True + trust_env=False explicitly selects its default CA bundle.
_COOKIE_HEADER = re.compile(r"(?i)(\\b(?:set-cookie|cookie)\\s*[:=]\\s*)[^\\r\\n]+")
# Replace the entire header value before generic assignment redaction.
```
Use actual installed SDK metadata APIs; preserve existing tool output conversion and argument model declarations. Re-review the fixes independently.
3. VERIFY: `uv sync --locked`; `PYTHONPATH=src uv run --locked pytest`; `uv run --locked ruff check .`; `uv run --locked pyright`; `uv build`; console help and actual Spark EOF smoke with a fresh temporary root; strict change/all-changes/all-specs validation. `PYTHONPATH=src uv run --locked pytest -m integration tests/integration/test_spark_server.py` reports skipped if deployment gate missing. Exact results are recorded in verification.md. PYTHONPATH is a development-test workaround for this host's reappearing hidden .pth flags, never a production launch instruction.
4. COMMIT: `git add src/mcp_stdio/core/server.py src/mcp_stdio/plugins/spark tests/unit/plugins/spark openspec/changes/add-spark-event-log-download`; `git commit -m "fix(spark): preserve exact scope and isolate credential boundaries"`, then commit final verification evidence and gated task completion.
Self-review 4.2: fixes address reproduced scope/security defects without adding product capabilities.


## Task 5.1 — Explicit deployment TLS verification switch

Mode: inline executing-plans, one coupled config/transport task. The only completion checkbox is tasks.md.
Files: src/mcp_stdio/plugins/spark/{config,http_client}.py; tests/unit/plugins/spark/{test_config,test_http_client}.py; README.md, README.zh-CN.md, docs/examples/spark.{yaml,json}, docs/architecture/{modules,runtime-flow}.md.
Consumes: existing SparkSettings, load_config, SparkHttpClient._ensure_client.
Produces: strict boolean `verify_tls: bool = True`, env SPARK_VERIFY_TLS; no tool-schema changes.

1. RED: add config default, file false/env true override, env false, invalid values tests. Parametrize the existing lazy client capture test with verify_tls True/False and assert `options[0]["verify"] is verify_tls`. Run `PYTHONPATH=src uv run --locked pytest tests/unit/plugins/spark/test_config.py tests/unit/plugins/spark/test_http_client.py`; expect missing field/unknown setting failures.
2. GREEN: add `verify_tls: bool = True` to SparkSettings. In _ensure_client use `context: ssl.SSLContext | bool = self._settings.verify_tls`; `if context and ca_path: context = ssl.create_default_context(cafile=ca_path)`. Run the same command; expect PASS. Existing CA validation and no-redirect controls remain.
3. Document default true and `export SPARK_VERIFY_TLS=false`, with explicit absence of server identity verification; update example defaults and architecture ownership. Review diff against spec; no dependencies or other plugins changed.
4. Fresh verification: `uv sync --locked`; `PYTHONPATH=src uv run --locked pytest`; `uv run --locked ruff check .`; `uv run --locked pyright`; `uv build`; `PYTHONPATH=src uv run --locked mcp-stdio --help`; strict OpenSpec change/changes/specs validation. Real MCP stdio call with deployment env SPARK_VERIFY_TLS=false, refresh=true; report authentication result without exposing raw response or credentials.
5. Gate task only after required checks and docs pass; record real download outcome separately in verification.md. Commit scoped files with `git commit -m "feat(spark): allow explicit TLS verification opt-out"`.
Self-review: default verification, opt-out, file/env validation, unchanged MCP input and redirection covered. No unresolved design gaps.
