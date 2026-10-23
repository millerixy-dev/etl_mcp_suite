# Stdout validation micro-plan

## Apply execution decision — 2026-10-14

Use inline executing-plans for this change: contracts, URL policy, publication and composition share interfaces/files and are sequential. Review uses requesting-code-review after implementation. Work in the existing development branch; tasks.md alone tracks completion.

## Task 2.1 — Contracts and service

Files: create `src/mcp_stdio/plugins/spark/executor_log_models.py` and `tests/unit/plugins/spark/test_executor_logs.py`; modify spark/config.py, gateway.py, service.py, core/errors.py and test_config.py. No HTTP or filesystem acquisition in the service.

1. RED: tests construct `SparkExecutorLogRequest(application_id="application_1_42", attempt_id="2", executor_id="driver")`, reject coerced tail/extra fields, assert exactly 12 result fields. Fake gateway records `fetch(request, deadline=...)`, returns a named result, raises an existing eventlog error, or blocks until cancellation. Assert new operation/validated identifiers, timeout and cleanup. Config tests enable `/yarn/nodemanager/node` plus `["http://*.nodes.example:8042"]`, reject incomplete/unsafe settings and retain old defaults.
2. Run `PYTHONPATH=src uv run --locked pytest -q tests/unit/plugins/spark/test_executor_logs.py tests/unit/plugins/spark/test_config.py` and confirm missing contracts/new settings fail.
3. GREEN: implement frozen strict request/result models, `SparkExecutorLogGateway.fetch/close`, service validation/one deadline/remapped errors, operation allowlist and two locally validated settings. Example service invocation: `await gateway.fetch(request, deadline=deadline)` inside `asyncio.wait_for` using the original remaining budget. No new dependency.
4. Verify `PYTHONPATH=src uv run --locked pytest -q tests/unit/plugins/spark/test_executor_logs.py tests/unit/plugins/spark/test_config.py tests/unit/core/test_errors.py tests/contract/test_architecture.py`; inspect diff, then commit only task files after passing. Gate task2.1 afterwards.

> Use superpowers:executing-plans for this tightly coupled validation task. OpenSpec tasks.md remains the only milestone checklist.

**Goal:** Complete task 1.1 against the user-authorized Driver stdout URL, reusing existing Spark authentication and redaction.

**Architecture:** No production changes. A private temporary validation program calls SparkHttpClient._ensure_client/_login and files.redact_event/credential_values, collects a bounded HTML response in memory, extracts stdout and atomically publishes private redacted evidence.

**Tech stack:** Existing locked uv environment, httpx, Pydantic and Python HTMLParser/hashlib/pathlib.

## Global constraints

Python >=3.10, uv exclusively, no secrets/raw HTML/raw log text in outputs or committed files; credentials only in process memory; authorization and TLS settings reuse the prior user-authorized same-gateway validation. Fixed 8MiB response and 1MiB output, one 60s deadline. No URL guessing or automatic redirects. Requested tail is 65536 bytes. The known destination is application_1783000588461_687089, attempt 2, Driver stdout.

## Task 1.1 — Real stdout evidence

Files: read existing spark/config.py, http_client.py, files.py and tests/unit/plugins/spark/test_knox_auth.py; update only this change's planning artifacts and verification.md. Create the experiment program in a private temporary directory and remove it after verification; output evidence under the user's private local cache, never the Git checkout.

Consumes: SparkSettings/SparkSecrets; SparkHttpClient._login(client, download_url, deadline); redact_event({"Event":"DiagnosticText","text":body}, credential_values(secret_values)). Produces: stdout.log and manifest.json, safe structural summary only.

1. Run `PYTHONPATH=src uv run --locked pytest -q tests/unit/plugins/spark/test_knox_auth.py tests/unit/plugins/spark/test_files.py`; existing authentication/redaction contracts must pass.
2. Before adding extraction logic, run the temporary program's synthetic checks against an empty extraction stub: a matching stdout pre block must yield `last line without newline`; assert the expected failure. No network in this step.
3. Implement HTMLParser extraction in the experiment only. Require validated request URL identity, Log Type stdout and one associated body pre; reject login form, ignore template-only pre, and never use IDs inside log text as identity evidence. Run the same checks, verify UTF-8/entities and EOF-final-line preservation, then use existing redact_event to remove synthetic password and known secret. No bespoke streaming redactor.
4. Read only the already user-designated credential file in memory. Parse URL/USER_NAME/PASSWORD without executing its contents. Require its origin to match the user's stdout destination. Instantiate the existing settings/secrets and use exactly the existing Knox SSO POST; do not reveal credential values, query auth codes or cookies. Use existing authorized verify_tls=false only for this one live validation; no persistent configuration change.
5. GET the exact user-provided JobHistory stdout URL with start=-65536 and Accept-Encoding identity. Never follow Location automatically; report safe failure if status or recognized log body is missing. Preserve raw HTML in bounded memory only, redact extracted text with configured and acquired cookie values.
6. Publish UTF-8 stdout.log plus one manifest in a 0700/0600 private cache directory. Record container, request range, source metadata, output size/hash and downloaded_at, with credentials redacted from provenance. Independently reopen output and verify hash, permissions and known-secret absence. Run fresh existing tests plus strict OpenSpec checks. Only then gate task 1.1; later public-tool tasks stay pending.

Verification commands: the pytest command above; `openspec validate add-spark-executor-log-fetch --strict`; `openspec validate --changes --strict`; `openspec validate --specs --strict`; `git diff --check`. Record safe actual results in verification.md. The temporary experiment is not a public MCP tool and is not committed as production code.

## Task 2.2 — Verified URL resolution and bounded acquisition

Files: create spark/executor_logs.py (one focused adapter with private URL/HTML helpers); add authenticated context reuse to spark/http_client.py; extend test_executor_logs.py. Consume the task2.1 models/gateway and existing VerifiedEventLogReader, SparkHttpClient and redact_event. Production acquisition remains unwired until task2.3.

1. RED: call `_LogRoute(settings, request(), original_url).url` for an allowlisted NodeManager URL and validate `redirect(current, location)` for JobHistory. Assert encoded owner/container identity, overwrite start, reject backend bypass/foreign origin/changed identity/SSO/duplicate query and pin history upstream. Resolve the last matching registration with a verified-reader visitor; missing stream must not trigger refresh.
2. RED: `parse_log_html(raw, "stdout", container)` must return decoded text/optional source length/coverage; template whitespace pre is ignored, only metadata-bound pre accepted. Include empty stream, no-newline EOF, login/ACL/missing pages, metadata conflict, multiple versions and malformed UTF-8. `_receive` tests use MockTransport plus existing Stream for max3 redirects, cycles, one Basic login, Cookie scope, cumulative8MiB, acquired-cookie redaction and cancellation.
3. Run `PYTHONPATH=src uv run --locked pytest -q tests/unit/plugins/spark/test_executor_logs.py` and confirm missing adapter behavior. Implement only these contracts: shared `SparkHttpClient.authenticated(url, deadline)` context calls the existing login and clears cookies; actual GET always uses the gateway; bounded HTMLParser collects external metadata separately from pre content. Response bodies never enter error text/files. Adapter uses one absolute deadline throughout.
4. Verify `PYTHONPATH=src uv run --locked pytest -q tests/unit/plugins/spark/test_executor_logs.py tests/unit/plugins/spark/test_knox_auth.py tests/unit/plugins/spark/test_http_client.py tests/unit/plugins/spark/test_files.py`; existing eventlog rejects redirect. Fresh lint/types and diff review before commit and task gate. Publication is deliberately left for task2.3, not stubbed as success.

## Task 2.3 — Private publication, lifecycle and MCP composition

Files: extend spark/executor_logs.py, plugin.py, tools.py, tests/unit/plugins/spark/test_executor_logs.py, test_tools.py, test_plugin.py, tests/contract/test_spark_stdio.py and import_rules.py/test_architecture.py. Reuse the existing eventlog gateway owner; no second root lock.

1. RED: real fake-HTTP acquisition invokes `adapter.fetch(request(), deadline=...)`, reopens log/manifest, verifies 0700/0600, hash and 12 result keys, provenance, secret absence, repeated calls create distinct directories. Reject symlink descendants and corrupt/mismatched evidence; injected write/rename failures remove staging only. Cancellation/timeout and close cancel/await workers before source lock release. Output expansion >1MiB trims complete leading logical lines, EOF remains, known truncated source removes unsafe initial fragment. Old config returns CONFIG_ERROR without source access.
2. RED: stdio exact tool union includes fetch_spark_executor_log, strict five-input schema and new safe error operation. Add architecture source tests forbidding service imports of executor_logs. Run `PYTHONPATH=src uv run --locked pytest -q tests/unit/plugins/spark/test_executor_logs.py tests/unit/plugins/spark/test_tools.py tests/unit/plugins/spark/test_plugin.py tests/contract/test_spark_stdio.py tests/contract/test_architecture.py tests/unit/test_registry.py`.
3. GREEN: implement bounded line-preserving processing, one owned-worker set/lock, descriptor-relative private directory/file creation and atomic rename. `fetch` checks enabled config before eventlog access, uses unchanged deadline, maps filesystem errors safely. Manifest contains the 12 public fields plus exact source/provenance/processing metadata; result never contains text. Wire service/adapter into runtime, close logs then inspector then the root-lock owner. Tool translates service result/errors only.
4. Verify `PYTHONPATH=src uv run --locked pytest -q tests/unit/plugins/spark tests/contract/test_spark_stdio.py tests/contract/test_architecture.py tests/unit/test_registry.py`, lint/types and diff; fresh review before commit and gate.

## Task 3.1 — Configuration and operational documentation

Files: docs/examples/spark-executor-logs.yaml and .json; README.md/README.zh-CN.md; docs/architecture/runtime-flow.md/modules.md; tests/unit/plugins/spark/test_config.py. No runtime behavior changes.

1. RED: load each new example through existing `_load`, assert only the two new fields and round-trip equivalent JSON-list environment values. Run `PYTHONPATH=src uv run --locked pytest -q tests/unit/plugins/spark/test_config.py -k executor_example`; expected missing example files.
2. GREEN: create YAML/JSON with history.example.invalid gateway mount, dedicated /var/tmp cache, verified TLS, optional CA comment, `/yarn/nodemanager/node` deployment placeholder and two minimal placeholder authority rules; Cookie secret is an environment-variable name. Add equivalent env-only start command. Document strict inputs, both Driver stdout and executor stderr calls, exact12-field result, coverage/limits, missing evidence explicit refresh, private evidence retention, recognized HTML limitation, Basic/Cookie reuse and log-only redirects. No new user credentials/routes are inferred.
3. Update architecture views with service/gateway/adapter ownership and log-client/worker close before existing directory owner. Verify `PYTHONPATH=src uv run --locked pytest -q tests/unit/plugins/spark/test_config.py tests/unit/test_package.py`, `openspec validate add-spark-executor-log-fetch --strict`, manual design-to-doc field comparison and `git diff --check`; commit docs/config tests only after task2.3 gate.

## Task 3.2 — Explicit live stdio opt-in

Files: create tests/integration/test_spark_executor_logs.py; extend tests/integration/test_opt_in.py. No production change.

1. RED: import live entry `test_spark_executor_stdout`; remove each required opt-in/application/attempt/executor/history/cache/log-route/allowlist/auth variable in turn and assert pytest.skip before `_run_stdout` is called. Also reject flag values other than literal1; complete Basic authentication reaches the runner without constructing an HTTP gateway in the parent.
2. Run `PYTHONPATH=src uv run --locked pytest -q tests/integration/test_opt_in.py` and confirm missing live module/entry failures.
3. GREEN: gate all prerequisites, load existing SparkSettings/SparkSecrets locally, then use SDK stdio_client and ClientSession to launch `sys.executable -m mcp_stdio --plugin spark` with environment settings/auth, initialize, call fetch_spark_executor_log with exact identity/log_type=stdout. Check no MCP error, parse named result and independently verify hash, size, manifest, private modes and configured-secret absence without printing body or credentials. Close session/process with async context managers. Missing deployment prerequisites skip.
4. Verify gate suite and `PYTHONPATH=src uv run --locked pytest -m integration tests/integration/test_spark_executor_logs.py`; report live skip accurately when opt-in is absent. No credential-file reader is added to shipped tools/tests.

## Task 3.3 — Whole-change release verification

Files: verification.md and tasks.md only unless a fresh check identifies a concrete defect. Review baseline3dce17e through current worktree covers contracts/settings, authentication reuse, bounded acquisition/publication, MCP composition, docs and explicit live gates. Review findings require a regression test before fixes, fresh affected verification and re-review.

Run exactly:

```sh
uv sync --locked
PYTHONPATH=src uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked pyright
uv build
PYTHONPATH=src uv run --locked mcp-stdio --help
openspec validate add-spark-executor-log-fetch --strict
openspec validate --changes --strict
openspec validate --specs --strict
git diff --check
```

Expected: all unit/contract and opt-in-gate tests pass, no lint/type errors, wheel/sdist built, help exit0, strict validations pass. Additionally launch `uv run --locked mcp-stdio --plugin spark` with a dedicated temporary private cache, SPARK_HISTORY_SERVER_URL=https://127.0.0.1:1/gateway/test/sparkhistory, route=/yarn/nodemanager/node and minimal synthetic allowlist, stdin=/dev/null. Assert exit0, stdout empty and subsequent owner can reopen the same cache; no unreachable network is contacted during startup. Record exact final counts and the explicit live integration skip separately from prior task1.1 live evidence. Only gate task3.3 after review and all checks pass.
