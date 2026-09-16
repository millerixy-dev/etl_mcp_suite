# Zeppelin Notebook Interpreter Restart — Per-task Micro-plans

## Global Constraints

- OpenSpec change `support-zeppelin-notebook-interpreter-restart` is the source of truth; tasks run in `tasks.md` order.
- Use Python 3.10-compatible syntax and `uv run --locked` for verification.
- Follow strict RED -> GREEN -> REFACTOR TDD and commit each task separately.
- Preserve opaque setting IDs exactly; do not trim, case-fold, coerce scalars, or apply the paragraph interpreter-name regex.
- Keep paragraph interpreter validation unchanged and default restart permission to deny.
- Do not touch unrelated untracked `.codex` files or introduce network access during configuration validation.

### Task 1: OpenSpec 1.1 — Opaque restart setting IDs in configuration

**OpenSpec task:** `1.1 Following Apply preflight, write and run failing tests for opaque restart IDs (including numeric-leading/reserved characters), exact allowlist comparison, cross-field ID length, no scalar coercion, JSON-array env overrides, and unchanged paragraph interpreter validation; implement the minimal config/model changes and refactor with tests green.`

**Files:**

- Modify: `tests/unit/plugins/zeppelin/test_config.py`
- Modify only if an uncovered model regression requires it: `tests/unit/plugins/zeppelin/test_models.py`
- Modify: `src/mcp_stdio/plugins/zeppelin/config.py`
- Do not modify service, gateway, HTTP, tool, or plugin wiring in this task.

**RED:**

1. Add focused tests proving `restartable_interpreter_settings` preserves IDs such as `2AY6GV7Q3` and `../spark?scope=note#v1`, compares duplicates case-sensitively, rejects empty/control-containing/overlong IDs, and rejects numeric/boolean entries without coercion.
2. Add a cross-field test showing a setting ID longer than a configured `max_opaque_id_chars` is rejected while the same ID is accepted when the bound permits it.
3. Add a plugin-prefixed environment override test using `ZEPPELIN_RESTARTABLE_INTERPRETER_SETTINGS` and a lower-priority generic override/file value; verify exact JSON-array strings and precedence. Include an invalid scalar override case.
4. Retain or add a model assertion that paragraph interpreter names still reject numeric-leading/reserved syntax while `validate_opaque_id` accepts it.
5. Run `uv run --locked pytest tests/unit/plugins/zeppelin/test_config.py tests/unit/plugins/zeppelin/test_models.py -q` and record the expected failures caused by the existing interpreter regex and list-element coercion.

**GREEN / REFACTOR:**

1. Replace only the restart allowlist conversion/validation path with strict string collection handling. Keep the existing tuple conversion behavior for the other typed collections.
2. Validate each restart ID as a non-empty, control-free opaque string and enforce uniqueness by exact case-sensitive value.
3. Add model-level cross-field validation against `max_opaque_id_chars` so field order and environment/file input paths behave identically.
4. Keep configuration error text fixed and value-free; preserve immutable tuple output and no-network loading.
5. Refactor helpers only where it reduces duplication without changing other setting semantics.

**Verification:**

- Required: `uv run --locked pytest tests/unit/plugins/zeppelin/test_config.py tests/unit/plugins/zeppelin/test_models.py -q`
- Also run: `uv run --locked ruff check src/mcp_stdio/plugins/zeppelin/config.py tests/unit/plugins/zeppelin/test_config.py tests/unit/plugins/zeppelin/test_models.py`
- Commit the task with a focused message and write TDD evidence to the assigned implementation report.

### Task 9: OpenSpec 4.2 — Contextual notebook interpreter restart

**OpenSpec task:** `4.2 Write and run failing service/HTTP tests for notebook-mode restart: local allowlist checked before all network access, fresh selected-binding membership, precise noteId body and encoded setting path, empty/absent/unselected binding rejection, no context-dropping fallback, one overall deadline and one PUT, no auto paragraph execution, non-retryable uncertain result, and strict matching four-field response. Preserve omitted/null legacy calls and mappings with regression tests; implement and refactor.`

**Files:**

- Modify: `tests/unit/plugins/zeppelin/test_service.py`
- Modify: `tests/unit/plugins/zeppelin/test_http_client.py`
- Modify: `src/mcp_stdio/plugins/zeppelin/service.py`
- Modify: `src/mcp_stdio/plugins/zeppelin/http_client.py`
- Modify gateway/domain helpers only when the tests demonstrate a missing contract seam.
- Do not modify MCP tool schemas yet, run paragraphs, cache bindings, or add a second transport path.

**RED:**

1. Add service-fake tests proving `setting_id` now uses the bounded opaque-ID validator, `notebook_id=None` and omission preserve the legacy call, a non-null notebook ID is validated, exact allowlist membership is checked before every gateway/network call, and reserved/numeric-leading IDs are preserved without normalization.
2. Add adapter tests for contextual restart under one serialized discovery-lock scope: fresh readable-notebook/ticket/WebSocket discovery must contain an exact `setting_id` with `selected=true`; valid empty, absent, or unselected membership prevents every restart PUT and returns non-retryable `INVALID_INPUT` attributed to restart. Duplicate setting IDs are malformed upstream data and return `UNEXPECTED_RESPONSE`, as required by the capability spec and design error table.
3. Prove the sole PUT targets `/interpreter/setting/restart/{setting_id encoded exactly once}` with exactly compact-equivalent JSON `{"noteId": notebook_id}`; notebook ID remains JSON data. Assert there is no paragraph execution, setting-wide fallback, reconnect, login/restart retry, or second PUT on discovery/PUT/response failure.
4. Use deterministic delayed lock, HTTP, and WebSocket fakes to prove one `request_timeout_seconds` deadline starts before lock acquisition and covers login, precheck, ticket, socket query, cleanup state, and PUT. All contextual failures, including timeout/connection uncertainty after PUT begins, are non-retryable and keep restart operation plus safe setting/notebook identifiers.
5. Add legacy regression tests for omitted/null calls: no discovery request/socket, no JSON body, existing 401/403, >=400, timeout, connection mappings and retryability remain unchanged.
6. Add strict restart response tests for actual non-empty control-free strings only, matching returned ID, ID/configured length bounds, name/group/status <=256, extra fields discarded, and complete compact `ensure_ascii=False` UTF-8 result at exact `max_result_bytes`/one byte over. Reject coercible, missing, mismatched, control, oversized, or over-budget responses as non-retryable `UNEXPECTED_RESPONSE` without repeating PUT.
7. Add cancellation/shutdown regression coverage where contextual restart waits for the lock or is inside discovery/PUT: cancellation propagates after bounded cleanup, close rejects/cancels active contextual work, releases the lock/resources, and leaves no background task.
8. Run `uv run --locked --no-sync pytest tests/unit/plugins/zeppelin/test_service.py tests/unit/plugins/zeppelin/test_http_client.py -q` before production edits and retain the functional RED.

**GREEN / REFACTOR:**

1. Update the service signature to `restart_interpreter(setting_id, notebook_id=None)`, validate the setting and optional notebook with `validate_opaque_id`, filter safe identifiers, enforce the exact local allowlist before awaiting the gateway, and pass the validated optional notebook unchanged.
2. Extend the gateway adapter signature. Keep legacy restart on its existing direct path. For contextual restart, derive one monotonic deadline at public entry, acquire the existing discovery lock within that budget, call `_discover_locked` with restart attribution, require exact selected membership, then issue exactly one contextual PUT before releasing the lock.
3. Reuse the existing lifecycle ownership/cancellation/close machinery without recursive lock acquisition. Track contextual tasks with discovery tasks so shutdown cancels both; preserve `CancelledError`, bounded cleanup, and rejection of new work after close.
4. Add a remaining-budget wrapper for every contextual stage, including the PUT. Do not reset HTTP timeout, retry, reconnect, or fall back to a bodyless restart. Map all contextual errors to non-retryable safe restart errors while retaining the specified category.
5. Send `{"noteId": notebook_id}` only in contextual mode. Encode only the setting path segment exactly once; never place the notebook ID in the path or socket URL.
6. Centralize strict restart-result parsing for both modes: require the four public fields as bounded strings, exact requested ID, discard extras, serialize the full public model compactly with `ensure_ascii=False`, and enforce `max_result_bytes` without truncation. A failure after PUT remains an uncertain non-retryable error and never repeats the request.
7. Keep the adapter/service dependency boundaries and legacy behavior intact; refactor only after the focused suite is green.

**Verification:**

- Required: `uv run --locked --no-sync pytest tests/unit/plugins/zeppelin/test_service.py tests/unit/plugins/zeppelin/test_http_client.py -q`
- Also run affected lifecycle/plugin tests: `uv run --locked --no-sync pytest tests/unit/plugins/zeppelin/test_websocket_client.py tests/unit/plugins/zeppelin/test_plugin.py -q`
- Also run Ruff over changed production/tests and scoped Pyright for `service.py`, `http_client.py`, `gateway.py`, `plugin.py`, and the two task test files; run full Pyright and report remaining baseline separately.
- Commit the task with a focused message and write TDD evidence to the assigned implementation report.

### Task 2: OpenSpec 1.2 — Binding models, gateway signatures, and safe error mappings

**OpenSpec task:** `1.2 Write and run failing tests for immutable InterpreterBinding/InterpreterBindingsResult, their exact fields/types/limits, the gateway's new discovery and optional notebook restart signatures, and safe operation/identifier mappings (including IDs exceeding the core limit); implement those shared contracts and update fake gateways so existing tests stay green.`

**Files:**

- Modify: `tests/unit/plugins/zeppelin/test_models.py`
- Modify: `tests/unit/plugins/zeppelin/test_service.py`
- Modify: `tests/unit/core/test_errors.py`
- Modify: `src/mcp_stdio/plugins/zeppelin/models.py`
- Modify: `src/mcp_stdio/plugins/zeppelin/gateway.py`
- Modify: `src/mcp_stdio/core/errors.py`
- Do not implement service discovery, HTTP, WebSocket, MCP tool wiring, or notebook-mode restart behavior in this task.

**RED:**

1. Add model tests for immutable, extra-forbid, strict `InterpreterBinding` with exactly `setting_id`, `name`, `interpreters`, `selected`, `restart_allowed`, and `InterpreterBindingsResult` with exactly `notebook_id`, `bindings`.
2. Cover numeric/boolean coercion rejection, empty/control-containing/overlong IDs and names, 256-binding and 64-interpreter limits, duplicate public setting IDs, tuple normalization/immutability, and exact JSON output.
3. Add protocol/signature checks and update the service fake contract for gateway `get_interpreter_bindings(notebook_id)` and `restart_interpreter(setting_id, notebook_id=None)` without adding service behavior yet.
4. Add error tests for public operation `get_interpreter_bindings`, its allowed `notebook_id`, restart's allowed `{setting_id, notebook_id}`, rejection of disallowed/sensitive keys, and a safe mapping/filter helper that omits rather than truncates identifiers longer than the core 256-character public limit.
5. Run `uv run --locked pytest tests/unit/core/test_errors.py tests/unit/plugins/zeppelin/test_models.py tests/unit/plugins/zeppelin/test_service.py -q` and record the expected contract failures.

**GREEN / REFACTOR:**

1. Add the smallest domain models and, if needed for the gateway/service boundary, one immutable internal binding record with only `setting_id`, `name`, `interpreters`, and `selected`; keep transport types out of models.
2. Apply explicit strict typing, fixed protocol ceilings, exact fields, frozen models, and value-free validation messages. Keep the configured `max_opaque_id_chars` check in service/config; domain ceilings must not exceed the approved 4096 maximum.
3. Extend `ZeppelinGateway` with discovery and optional notebook restart signatures, and update fakes only enough to satisfy the protocol contract and retain existing tests.
4. Extend the closed operation enum and identifier allowlist. Add a reusable safe identifier filtering function for caller-supplied opaque IDs; retain strict rejection for unsafe direct `ToolError` construction.
5. Keep behavior changes out of the application service until Tasks 4.1/4.2.

**Verification:**

- Required: `uv run --locked pytest tests/unit/core/test_errors.py tests/unit/plugins/zeppelin/test_models.py tests/unit/plugins/zeppelin/test_service.py -q`
- Also run: `uv run --locked ruff check src/mcp_stdio/core/errors.py src/mcp_stdio/plugins/zeppelin/models.py src/mcp_stdio/plugins/zeppelin/gateway.py tests/unit/core/test_errors.py tests/unit/plugins/zeppelin/test_models.py tests/unit/plugins/zeppelin/test_service.py`
- Also run focused type checking on the changed production modules and tests; record pre-existing failures separately from regressions.
- Commit the task with a focused message and write TDD evidence to the assigned implementation report.

### Task 3: OpenSpec 2.1 — Session-aware notebook precheck and fresh ticket acquisition

**OpenSpec task:** `2.1 Write and run focused failing HTTP-mock tests for readable/existing notebook precheck with matching response ID, missing/denied notebook, bounded streamed response, discarded paragraph content, correctly form-encoded credentials, fresh ticket acquisition in the same session, string-array roles validation, anonymous policy, and attribution to the initiating operation. Implement the smallest session/ticket helpers without changing unrelated tool behavior, then refactor.`

**Files:**

- Modify: `tests/unit/plugins/zeppelin/test_http_client.py`
- Modify: `src/mcp_stdio/plugins/zeppelin/http_client.py`
- Modify a transport-neutral model/helper file only if needed for a private non-repr authentication value; do not expose ticket data through public models.
- Do not add the WebSocket dependency/client, derive `/ws`, select cookies/origin, or implement binding parsing in this task.

**RED:**

1. Add HTTP mock tests for one discovery-preparation flow using a caller-supplied initiating operation (`get_interpreter_bindings` and `restart_interpreter` attribution): optional login, `GET /notebook/{encoded_id}`, then `GET /security/ticket`, all through the same lazy `httpx.AsyncClient` session.
2. Prove the notebook response must be an OK envelope with an object body whose exact `id` matches the requested ID; 403 maps to `PERMISSION_DENIED`, 404 maps to `NOT_FOUND`, and neither failure fetches a ticket.
3. Prove notebook content/paragraphs are discarded and streamed bytes are capped by `max_response_bytes`, including missing/lying `Content-Length`; response streams close on success and failure.
4. Prove credentials are sent as correctly form-encoded `userName` and `password` values, login happens only when the configured pair exists, anonymous mode skips login, and ticket acquisition still relies on upstream anonymous policy.
5. Prove every discovery preparation obtains a fresh ticket and validates non-empty bounded string `principal`/`ticket` plus `roles` as a JSON-array string containing only strings. Missing, malformed, scalar, object, nested, or non-string role entries fail as `UNEXPECTED_RESPONSE` before any future socket work.
6. Prove login/precheck/ticket errors retain the initiating operation and only safe filtered identifiers; no raw notebook content, credential, ticket, or roles values appear in errors/logs.
7. Run `uv run --locked pytest tests/unit/plugins/zeppelin/test_http_client.py -q` and record expected failures before production edits.

**GREEN / REFACTOR:**

1. Parameterize session authentication with the initiating operation/identifiers instead of the existing hard-coded create operation, preserving all existing tool mappings.
2. Use httpx form data encoding for login rather than interpolating credential text.
3. Add a small plugin-private, non-repr ticket/auth context and a discovery preparation helper that validates notebook readability/existence and fresh ticket metadata on the existing session.
4. Read discovery HTTP bodies incrementally with a hard cumulative byte ceiling and guaranteed response closure. Parse only after the bounded read; discard notebook fields other than matching `id`.
5. Use fixed safe error mappings and `safe_error_identifiers`; keep secrets and upstream body text out of exceptions and logs.
6. Refactor only enough to share existing request/error plumbing without changing unrelated REST request shapes or adding network retries.

**Verification:**

- Required: `uv run --locked pytest tests/unit/plugins/zeppelin/test_http_client.py -q`
- Also run: `uv run --locked ruff check src/mcp_stdio/plugins/zeppelin/http_client.py tests/unit/plugins/zeppelin/test_http_client.py`
- Also run: `uv run --locked pyright src/mcp_stdio/plugins/zeppelin/http_client.py`
- Commit the task with a focused message and write TDD evidence to the assigned implementation report.

### Task 4: OpenSpec 2.2 — WebSocket URL derivation and scoped handshake authentication

**OpenSpec task:** `2.2 Write and run failing tests for HTTP(S) /api to WS(S) /ws derivation, proxy-prefix preservation, fail-before-network for ambiguous mounts, and scoped Cookie/Origin handling. Implement the URL and private authentication context needed by discovery, then refactor.`

**Files:**

- Modify: `tests/unit/plugins/zeppelin/test_http_client.py`
- Modify: `src/mcp_stdio/plugins/zeppelin/http_client.py`
- Do not add the `websockets` dependency/client, perform a socket connection, parse binding frames, or expose handshake values through public models/results.

**RED:**

1. Add table-driven tests deriving `ws://host/ws` from `http://host/api` and `wss://host/proxy/ws` from `https://host/proxy/api`, preserving host, explicit port, and proxy prefix while replacing only the final literal `/api` path component.
2. Add fail-before-network tests for bases without terminal `/api`, lookalike suffixes (`/api-v2`, `/myapi`), root/custom mounts, or otherwise ambiguous mapping. Assert `CONFIG_ERROR`, initiating operation attribution, safe IDs, and zero HTTP calls.
3. Add private-context tests for exact WebSocket URL, HTTP(S) Origin (`scheme://authority`), and Cookie selection after login using the same `httpx` jar.
4. Prove cookie selection honors host-only/domain, path, Secure, expiry, and port/origin rules: only cookies that HTTPX would send to the same-origin HTTP(S) `/ws` target become the private Cookie header; unrelated-domain/path, expired, and Secure-over-HTTP cookies are excluded.
5. Prove redirect responses are rejected without following to another origin, `trust_env=False` remains set, credentials/tickets/cookies are never placed in URLs, public errors, repr, stdout, or stderr, and no alternate-origin request is sent.
6. Run `uv run --locked pytest tests/unit/plugins/zeppelin/test_http_client.py -q` and record expected failures before production edits.

**GREEN / REFACTOR:**

1. Add a pure, strict URL derivation helper using parsed URL components. Require the normalized path's final component to be exactly `api`; map only `http->ws` and `https->wss`; preserve authority/port/prefix; never guess or accept caller overrides.
2. Run derivation before authentication or any other network operation in discovery preparation and map ambiguity to safe non-retryable `CONFIG_ERROR` for the initiating operation.
3. Extend the plugin-private non-repr discovery context with derived WebSocket URL, exact HTTP(S) origin, and an optional scoped Cookie header selected from the existing HTTPX cookie jar against the corresponding HTTP(S) `/ws` target.
4. Delegate cookie domain/path/expiry/Secure matching to the standard cookie jar. Copy only the final Cookie value; do not expose arbitrary headers or transport objects.
5. Preserve `trust_env=False`, no redirect following, and existing Task 2.1 request/session behavior.

**Verification:**

- Required: `uv run --locked pytest tests/unit/plugins/zeppelin/test_http_client.py -q`
- Also run: `uv run --locked ruff check src/mcp_stdio/plugins/zeppelin/http_client.py tests/unit/plugins/zeppelin/test_http_client.py`
- Also run: `uv run --locked pyright src/mcp_stdio/plugins/zeppelin/http_client.py`
- Commit the task with a focused message and write TDD evidence to the assigned implementation report.

### Task 5: OpenSpec 3.1 — One-shot WebSocket binding query and strict parsing

**OpenSpec task:** `3.1 Write and run failing tests for the proposed websocket_client.py helper using injected fake connections: exact authenticated GET_INTERPRETER_BINDINGS envelope, isolated response without correlation echo, strict id/name/interpreters/selected parsing, empty lists, upstream order, duplicate IDs, extra-field discard, collection/name limits, frame/cumulative-byte limits, unrelated envelopes, binary/invalid JSON, AUTH_INFO, SESSION_LOGOUT, ERROR_INFO, and safe connection/handshake failure mapping. Add the direct dependency via uv add 'websockets>=15,<16', update uv.lock, implement the minimal adapter and refactor.`

**Files:**

- Create: `src/mcp_stdio/plugins/zeppelin/websocket_client.py`
- Create: `tests/unit/plugins/zeppelin/test_websocket_client.py`
- Modify through uv only: `pyproject.toml`, `uv.lock`
- Reuse: `InterpreterBindingRecord`, `ZeppelinGatewayError`, `ToolOperation`, and safe identifier filtering.
- Do not compose the helper into `ZeppelinHttpClient`, implement application-service discovery, add concurrency locking, or implement shutdown-race ownership in this task.

**RED:**

1. Create injected fake connector/connection tests for the exact compact JSON request envelope: `op=GET_INTERPRETER_BINDINGS`, `data.noteId`, server-issued principal/ticket/roles, and injected deterministic `msgId`; caller cannot add fields.
2. Prove a valid `INTERPRETER_BINDINGS` response without echoed `noteId`/`msgId` is accepted on the isolated connection, preserving binding and interpreter order; valid empty result returns an empty tuple.
3. Cover strict payload parsing of `id`, `name`, `interpreters[*].name`, and boolean `selected`; discard extra upstream fields; reject missing/coercible/wrong types, empty/control/overlong text, more than 256 bindings, more than 64 interpreter names, and duplicate setting IDs.
4. Cover at most 32 received application messages, `max_response_bytes` for each text frame and cumulative UTF-8 bytes, unrelated well-formed string-op envelopes within bounds, binary frames, invalid JSON/envelope/data, and malformed expected payloads.
5. Cover `AUTH_INFO`/`SESSION_LOGOUT` -> non-retryable `AUTHENTICATION_FAILED`, `ERROR_INFO` -> non-retryable `UPSTREAM_ERROR`, connection/premature close -> `CONNECTION_FAILED`, timeout -> `TIMEOUT`, and handshake 401/403/404/other status mappings without copying raw upstream text.
6. Assert connector arguments: exact URL/origin, only optional Cookie header, `proxy=None`, `compression=None`, `max_queue=1`, `max_size=max_response_bytes`, no redirect/reconnect iterator, and a silent private logger.
7. Run `uv run --locked pytest tests/unit/plugins/zeppelin/test_websocket_client.py -q` before production implementation and record the expected import/contract failure.

**GREEN / REFACTOR:**

1. Run `uv add 'websockets>=15,<16'` so `pyproject.toml` and `uv.lock` are resolved by uv; keep Python 3.10 compatibility and add no other dependency.
2. Implement a small injected-connector helper with one connection per query. Accept explicit private auth/context values and operation/error identifiers; do not retain them on a long-lived public object or include them in repr/logs.
3. Serialize one request and receive until the expected operation or a fixed bound. Count every application frame's UTF-8 byte length cumulatively; reject binary/invalid frames and limits without returning partial results.
4. Parse the verified schema into immutable `InterpreterBindingRecord` values, use its strict validators plus fixed collection/duplicate checks, and discard extra fields.
5. Map known library handshake/close/timeout exceptions to stable safe errors. Do not retry, reconnect, follow redirects, use environment proxies, or emit raw exception/frame/auth data.
6. Keep lifecycle implementation minimal here; Task 3.2 will establish the single end-to-end deadline, serialization, cancellation, bounded close/abort, and shutdown ownership.

**Verification:**

- Required: `uv sync --locked`
- Required: `uv run --locked pytest tests/unit/plugins/zeppelin/test_websocket_client.py -q`
- Required: `uv run --locked pyright`
- Also run: `uv run --locked ruff check src/mcp_stdio/plugins/zeppelin/websocket_client.py tests/unit/plugins/zeppelin/test_websocket_client.py`
- Commit the task with a focused message and write TDD evidence to the assigned implementation report.

### Task 6: OpenSpec 3.2 — End-to-end deadline, serialization, cancellation, and shutdown

**OpenSpec task:** `3.2 Write and run failing fake-transport tests for one end-to-end deadline (including lock waiting), serialized concurrent discovery, waiter cancellation, mid-connect/mid-receive cancellation, shutdown races, idempotent close, bounded close/abort, no surviving receive tasks, and no retry or redirect/auth forwarding. Implement and refactor lifecycle ownership in the helper/gateway.`

**Files:**

- Modify: `tests/unit/plugins/zeppelin/test_websocket_client.py`
- Modify: `tests/unit/plugins/zeppelin/test_http_client.py`
- Modify: `tests/unit/plugins/zeppelin/test_plugin.py`
- Modify: `src/mcp_stdio/plugins/zeppelin/websocket_client.py`
- Modify: `src/mcp_stdio/plugins/zeppelin/http_client.py`
- Modify plugin composition only if needed for an injected helper seam; do not add service/tool behavior.

**RED:**

1. Add deterministic fake-clock/transport tests showing one `request_timeout_seconds` wall-clock budget starts before lock acquisition and covers login, notebook precheck, ticket, WebSocket connect/send/receive; no stage resets the deadline.
2. Overlap two gateway discovery calls and prove per-process serialization includes HTTP/ticket work, each call uses its own session ticket/socket/response state, lock waiting consumes the second call's deadline, and cancellation of a waiting caller does not cancel the active caller.
3. Test caller cancellation during connect, send, receive, and lock wait. Cancellation must propagate after bounded cleanup, never become a success/error result, and leave no receive/background task.
4. Test gateway/runtime close while waiting, connecting, receiving, and immediately before/after query completion. Close rejects new discovery, cancels active work, closes owned WebSocket and HTTP resources, and is idempotent.
5. Test context-manager close that succeeds, raises, or hangs. Cleanup gets at most `min(5, request_timeout_seconds)` additional seconds; after expiry abort the underlying socket transport through a narrow injected seam. No cleanup exception/raw repr replaces caller cancellation or the primary safe error.
6. Assert no automatic reconnect/retry and no redirected or cross-origin auth forwarding. Connector invocation remains once per query with Task 3.1's secure options.
7. Run `uv run --locked pytest tests/unit/plugins/zeppelin/test_websocket_client.py tests/unit/plugins/zeppelin/test_http_client.py tests/unit/plugins/zeppelin/test_plugin.py -q` and retain functional RED before implementation.

**GREEN / REFACTOR:**

1. Introduce explicit lifecycle ownership around the one-shot helper: track active context/connection/receive task without exposing transport details outside the adapter; make close idempotent and bounded.
2. Add a gateway-level serialized discovery method implementing `get_interpreter_bindings`. Derive a monotonic deadline at entry and use Python-3.10-compatible `asyncio.wait_for` with remaining budget for lock and all upstream work.
3. Ensure one lock covers session login, notebook precheck, fresh ticket, socket query, and cleanup state. Never recursively acquire it; later notebook restart may call an internal already-locked path.
4. Preserve `CancelledError` and isolate waiter cancellation from active work. Track/cancel owned tasks explicitly; after every exit no receive task may survive.
5. On shutdown mark the gateway closed before cancellation, reject new discovery deterministically, clean active socket/query work within the cleanup allowance, then close HTTP client. Suppress cleanup failures without logging exception representations.
6. Keep discovery timeout/connection failures retryable and restart-attributed failures non-retryable. Do not implement service decoration or contextual restart PUT yet.

**Verification:**

- Required: `uv run --locked pytest tests/unit/plugins/zeppelin/test_websocket_client.py tests/unit/plugins/zeppelin/test_http_client.py tests/unit/plugins/zeppelin/test_plugin.py -q`
- Also run: `uv run --locked ruff check src/mcp_stdio/plugins/zeppelin/websocket_client.py src/mcp_stdio/plugins/zeppelin/http_client.py tests/unit/plugins/zeppelin/test_websocket_client.py tests/unit/plugins/zeppelin/test_http_client.py tests/unit/plugins/zeppelin/test_plugin.py`
- Also run scoped Pyright over changed production modules and task tests; run full `uv run --locked pyright` and report any remaining baseline separately.
- Commit the task with a focused message and write TDD evidence to the assigned implementation report.

### Task 7: OpenSpec 3.3 — Fail-closed secret scanning and silent transport errors

**OpenSpec task:** `3.3 Write and run failing tests with fake credential/ticket/cookie sentinels in exception messages, debug logs and returned string fields, including cleanup errors; implement fail-closed public-field sanitization and non-emitting transport logging, then refactor.`

**Files:**

- Modify: `tests/unit/plugins/zeppelin/test_websocket_client.py`
- Modify: `tests/unit/plugins/zeppelin/test_http_client.py`
- Modify: `src/mcp_stdio/plugins/zeppelin/websocket_client.py`
- Modify: `src/mcp_stdio/plugins/zeppelin/http_client.py`
- Modify private resource cleanup helpers only if a demonstrated cleanup-error leak requires it.
- Do not add public config fields, expose authentication data, or implement service/tool behavior.

**RED:**

1. Inject distinct username, password, principal, ticket, roles, and cookie sentinels and place each sentinel in every public binding string location (`setting_id`, setting `name`, interpreter name), including substring cases. Assert fail-closed `UNEXPECTED_RESPONSE` and no partial result.
2. Inject the same sentinels into connector/handshake/send/receive/close/abort/HTTP stream/client-close exception messages and library debug-log attempts. Assert fixed safe errors or propagated cancellation as appropriate, with no sentinel or raw protocol/header/frame/body in `str`, `repr`, `ToolError.to_dict`, captured logs, stdout, or stderr.
3. Test success responses and extra discarded upstream fields containing sentinels: approved public fields must be scanned; discarded fields must never be returned or logged. Empty sensitive values are ignored so they do not taint every string.
4. Test cleanup failure after a primary safe failure and after caller cancellation. Cleanup text must not replace the primary error/cancellation or emit through exception chaining, loop exception handlers, logs, stdout, or stderr.
5. Prove private auth/context/request objects remain non-repr and are cleared/released after the isolated query; no credentials/ticket/cookie persist in public/domain models or adapter results.
6. Run `uv run --locked pytest tests/unit/plugins/zeppelin/test_websocket_client.py tests/unit/plugins/zeppelin/test_http_client.py -q` and record functional RED before production edits.

**GREEN / REFACTOR:**

1. Pass a private tuple of configured secret values and current transient principal/ticket/cookie values from the HTTP gateway into the query helper; do not store it in public models or long-lived cache.
2. After strict binding parsing and before returning, scan every public string field for non-empty sensitive substrings. Any taint rejects the complete result with a fixed `UNEXPECTED_RESPONSE` path.
3. Keep transport logger disabled/non-propagating and never log exception representations, frames, headers, bodies, auth context, or cleanup failures. Consume late task outcomes without emitting them.
4. Preserve cancellation and primary error precedence through cleanup; remove transient references at query exit.
5. Avoid generic redaction-by-replacement in IDs/results because it would mutate upstream identity; reject instead.

**Verification:**

- Required: `uv run --locked pytest tests/unit/plugins/zeppelin/test_websocket_client.py tests/unit/plugins/zeppelin/test_http_client.py -q`
- Also run: `uv run --locked ruff check src/mcp_stdio/plugins/zeppelin/websocket_client.py src/mcp_stdio/plugins/zeppelin/http_client.py tests/unit/plugins/zeppelin/test_websocket_client.py tests/unit/plugins/zeppelin/test_http_client.py`
- Also run scoped Pyright over changed production modules and new/changed test regions; report existing full-suite diagnostics separately.
- Commit the task with a focused message and write TDD evidence to the assigned implementation report.

### Task 8: OpenSpec 4.1 — Public discovery service use case

**OpenSpec task:** `4.1 Write and run service-fake failing tests for input validation, discovery without execution/restart permission, local restart_allowed decoration, exact result-byte bounds, and safe operation attribution. Implement the discovery service use case and refactor.`

**Files:**

- Modify: `tests/unit/plugins/zeppelin/test_service.py`
- Modify: `src/mcp_stdio/plugins/zeppelin/service.py`
- Modify: `src/mcp_stdio/plugins/zeppelin/plugin.py` only to pass the existing `max_result_bytes` setting into the service constructor.
- Do not import HTTP/WebSocket modules into service or add MCP tool wiring.

**RED:**

1. Add service-fake tests for `get_interpreter_bindings(notebook_id)` validating strict non-empty/control-free opaque IDs bounded by `max_opaque_id_chars`, preserving numeric-leading/reserved syntax, and making zero gateway calls on invalid input.
2. Prove discovery works with empty paragraph execution and restart allowlists; every valid upstream binding remains visible in original order with `restart_allowed=false` and no restart/paragraph call.
3. Prove exact case-sensitive local ID membership sets `restart_allowed` independently per binding, without using setting name, interpreter names, group inference, selection, or upstream permission assumptions.
4. Prove empty upstream records return `InterpreterBindingsResult(notebook_id=..., bindings=())`, while gateway failures retain operation `get_interpreter_bindings`, safe notebook identifier filtering, category, and retryability.
5. Build compact `ensure_ascii=False` JSON test fixtures at exactly `max_result_bytes` and one byte over, including multibyte characters. Exact fit succeeds; overflow returns non-retryable `UNEXPECTED_RESPONSE` attributed to discovery without truncating/skipping entries.
6. Assert public result fields are exact, immutable, JSON serializable, and contain no transport/auth fields.
7. Run `uv run --locked pytest tests/unit/plugins/zeppelin/test_service.py -q` and retain functional RED before production edits.

**GREEN / REFACTOR:**

1. Add an async service method that validates notebook input, calls only `gateway.get_interpreter_bindings`, decorates each immutable record into `InterpreterBinding` using exact local allowlist membership, and returns `InterpreterBindingsResult`.
2. Add `max_result_bytes` to the service's validated constructor inputs and plugin composition. Do not couple it to transport response limits.
3. Serialize the complete public result compactly as UTF-8 with `ensure_ascii=False`; accept exact fit and fail the whole call with safe `UNEXPECTED_RESPONSE` on overflow.
4. Use fixed safe errors and `safe_error_identifiers` for caller IDs longer than the core public limit; do not catch or relabel gateway errors that already carry the correct discovery attribution.
5. Keep service imports limited to domain/gateway/core safety modules.

**Verification:**

- Required: `uv run --locked pytest tests/unit/plugins/zeppelin/test_service.py -q`
- Also run: `uv run --locked ruff check src/mcp_stdio/plugins/zeppelin/service.py src/mcp_stdio/plugins/zeppelin/plugin.py tests/unit/plugins/zeppelin/test_service.py`
- Also run scoped Pyright over changed production modules and service tests; report pre-existing diagnostics separately.
- Commit the task with a focused message and write TDD evidence to the assigned implementation report.

### Task 10: OpenSpec 5.1 — Nine-tool MCP wiring and public schemas

**OpenSpec task:** `5.1 Write and run failing tool/plugin tests for exactly nine tools, required notebook input on discovery, optional nullable notebook input on restart, exact public result schemas, safe errors, and zero network on startup/tool listing. Register/combine the new behavior and refactor.`

**Files:**

- Modify: `tests/unit/plugins/zeppelin/test_tools.py`
- Modify: `tests/unit/plugins/zeppelin/test_plugin.py`
- Modify: `src/mcp_stdio/plugins/zeppelin/tools.py`
- Do not change service/gateway semantics, architecture rules, docs/skills, or integration tests in this task.

**RED:**

1. Replace the shallow eight-tool assertions with an adapter fake and real FastMCP contract tests proving exact registration order/set of nine tools, including `get_interpreter_bindings` and all existing names, with no extra admin/binding-mutation tools.
2. Assert public signatures and FastMCP input schemas exactly: discovery requires one string `notebook_id`; restart requires string `setting_id` and optional `notebook_id` whose schema accepts string or null with default null; all other tool input schemas remain unchanged.
3. Assert exact output schemas: discovery uses `InterpreterBindingsResult.model_json_schema()` and restart remains `RestartInterpreterResult.model_json_schema()`; call both through FastMCP and compare structured/text JSON to the immutable public models with no ticket/cookie/roles/transport/group/status leakage in discovery.
4. Test adapter delegation for discovery and restart omission/null/value, preserving the optional notebook value exactly and making one service call.
5. Inject stable gateway errors and unexpected exceptions for both new paths. Assert serialized `FastMCPToolError` operation/category/retryability/safe identifiers, configured-secret filtering, no raw exception/sentinel, and no stdout/stderr emission.
6. Route raw invalid MCP inputs through a real service/fake gateway to prove strict non-coercion, pre-network validation, nullable-only restart notebook input, and zero gateway calls.
7. Construct the real plugin/runtime and list FastMCP tools while socket/DNS/HTTP/WebSocket entry points are patched to fail. Assert startup and listing make zero upstream calls; runtime close remains idempotent.
8. Run `uv run --locked --no-sync pytest tests/unit/plugins/zeppelin/test_tools.py tests/unit/plugins/zeppelin/test_plugin.py -q` and retain functional RED before production edits.

**GREEN / REFACTOR:**

1. Import the discovery result model, register `get_interpreter_bindings` once, and add a thin adapter method that delegates to the service and uses the existing stable error boundary with `GET_INTERPRETER_BINDINGS` attribution.
2. Extend the adapter restart method to accept a JSON-schema-explicit string-or-null `notebook_id=None` and pass it unchanged to the service. Keep `setting_id` required and avoid FastMCP/Pydantic coercion by retaining object-backed schema annotations.
3. Update registration docstrings/descriptions to the nine-tool contract and explain discovery/restart scope precisely enough for tool consumers without exposing implementation/auth details.
4. Reuse one small error-boundary helper only if it reduces duplication without changing current exception mapping, result typing, or stdout discipline.
5. Keep runtime construction and tool listing lazy and network-free; do not instantiate a WebSocket connection or obtain a ticket during registration/schema generation.

**Verification:**

- Required: `uv run --locked --no-sync pytest tests/unit/plugins/zeppelin/test_tools.py tests/unit/plugins/zeppelin/test_plugin.py -q`
- Also run affected service/contract smoke tests that exercise FastMCP schema/result behavior.
- Also run Ruff over changed production/tests and scoped Pyright over `tools.py`, `plugin.py`, and task tests; report existing test diagnostics separately.
- Commit the task with a focused message and write TDD evidence to the assigned implementation report.
