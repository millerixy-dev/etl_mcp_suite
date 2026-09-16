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
