## Context

See `proposal.md` for the motivation and scope. The existing gateway uses one lazy `httpx.AsyncClient`; its login discards the response body, and restart sends no JSON body. Application services and tool adapters already sit above a gateway protocol. No WebSocket client exists in this repository.

The capability is not yet consolidated in main specs. This change follows the implemented Zeppelin slice, restart, cancellation, and safety changes. It replaces only the overlapping tool-set, configuration, and restart requirements; all unrelated lifecycle and safety requirements remain authoritative. Archive/consolidate the predecessors before archiving this change, so a later archive cannot restore an older tool set or restart contract.

### Evidence and upstream contracts

The deployment's static bundle `app.452e77a4c556c7861195.js` was inspected on 2026-09-10. It explicitly calls `getInterpreterBindings(note.id)` on Settings open and sends `PUT .../interpreter/setting/restart/` plus `interpreter.id` with `{noteId: note.id}` after confirmation. This is static evidence from the deployed code, not an authenticated packet capture or a live restart test. Internal addresses, actual notebook titles, and credentials are not included in committed examples.

| Source | Verified contract and relevance |
|---|---|
| [Notebook controller, v0.10.1](https://github.com/apache/zeppelin/blob/v0.10.1/zeppelin-web/src/app/notebook/notebook.controller.js#L599) | Settings loads bindings; `restartInterpreter` at line 996 sends the selected ID and notebook context. |
| [WebSocket message service](https://github.com/apache/zeppelin/blob/v0.10.1/zeppelin-web/src/components/websocket/websocket-message.service.js#L353) | Query message is `GET_INTERPRETER_BINDINGS` with `data.noteId`; binding writes use a separate operation that this change never sends. |
| [WebSocket event factory](https://github.com/apache/zeppelin/blob/v0.10.1/zeppelin-web/src/components/websocket/websocket-event.factory.js#L32) | Message envelope carries server-issued principal, ticket, roles and a client `msgId`. |
| [NotebookServer](https://github.com/apache/zeppelin/blob/v0.10.1/zeppelin-server/src/main/java/org/apache/zeppelin/socket/NotebookServer.java#L513) | Query uses notebook settings filtered by the current user/roles and replies with `INTERPRETER_BINDINGS`, `data.interpreterBindings`. This handler does not echo `noteId` or the request `msgId`; a missing notebook can yield an empty list. Its WebSocket handler validates tickets before dispatch. |
| [InterpreterSettingsList](https://github.com/apache/zeppelin/blob/v0.10.1/zeppelin-server/src/main/java/org/apache/zeppelin/types/InterpreterSettingsList.java#L24) and [InterpreterInfo](https://github.com/apache/zeppelin/blob/v0.10.1/zeppelin-zengine/src/main/java/org/apache/zeppelin/interpreter/InterpreterInfo.java) | Upstream binding fields are `id`, `name`, `interpreters`, `selected`; each interpreter has a `name`. The binding DTO has no `group` or restart-status field, so the MCP must not invent these. |
| [SecurityRestApi](https://github.com/apache/zeppelin/blob/v0.10.1/zeppelin-server/src/main/java/org/apache/zeppelin/rest/SecurityRestApi.java#L62) | `GET /api/security/ticket` returns an OK envelope with string `principal`, string `ticket`, and `roles` encoded as a JSON-array string. |
| [NotebookRestApi](https://github.com/apache/zeppelin/blob/v0.10.1/zeppelin-server/src/main/java/org/apache/zeppelin/rest/NotebookRestApi.java#L308) | `GET /api/notebook/{noteId}` obtains a notebook through the notebook service. Use it to establish that the notebook is readable and exists, rather than interpreting an empty WebSocket response as proof of existence. |
| [InterpreterRestApi](https://github.com/apache/zeppelin/blob/v0.10.1/zeppelin-server/src/main/java/org/apache/zeppelin/rest/InterpreterRestApi.java#L184) | Restart with `noteId` checks notebook run/write/owner permission; omission closes the entire setting. Success returns the setting. |
| [InterpreterSetting](https://github.com/apache/zeppelin/blob/v0.10.1/zeppelin-zengine/src/main/java/org/apache/zeppelin/interpreter/InterpreterSetting.java#L240) | In this version post-processing assigns `id = name`; `group` is distinct. Preserve the returned ID, rather than deriving it from a group or shebang. |
| [Shiro template](https://github.com/apache/zeppelin/blob/v0.10.1/conf/shiro.ini.template#L115) | Authenticated users can reach the restart route; other interpreter REST routes default to administrator access. Deployment overrides remain possible. |
| [Frontend base URL service](https://github.com/apache/zeppelin/blob/v0.10.1/zeppelin-web/src/components/base-url/base-url.service.js) | REST sits beneath the application `/api`; WebSocket sits beneath application `/ws`, preserving a reverse-proxy prefix. |

## Goals / Non-Goals

**Goals:** model the notebook UI discovery/restart sequence as bounded MCP operations, keep ordinary user permissions, preserve existing clients, and isolate new transport details within the Zeppelin adapter.

**Non-Goals:** see the proposal. In particular, this is an outgoing Zeppelin WebSocket connection, not a change to MCP stdio transport. No long-lived subscription or binding mutation is introduced.

## Decisions

### D1. Separate discovery from restart, retain explicit IDs

Add `get_interpreter_bindings(notebook_id)`. The user or agent selects a returned `setting_id`; the service never chooses the first Spark setting or derives an ID from `%spark.sql`. Return all valid entries the upstream query returns, including locally non-restartable entries, in upstream order. `selected` retains the upstream boolean and is not interpreted as proof of an exclusive process binding. `restart_allowed` is exactly the local allowlist match and says nothing about upstream execution permission.

Extend restart with optional `notebook_id=None`. Omitting it or passing null preserves the existing setting-wide operation. A non-null value selects notebook mode and must be non-empty and valid; invalid or failed notebook mode never degrades into legacy mode. Tool descriptions and the canonical skill explain this distinction and use notebook mode in the recovery workflow. Keeping the parameter optional avoids a breaking MCP input-schema change; making it mandatory was considered but would break existing callers.

In notebook mode: validate both inputs and local allowlist before any network call, fetch current readable bindings, require one entry with an exact `setting_id` match and `selected=true`, then send one restart PUT with `noteId`. No bindings cache is retained. A failed lookup prevents the PUT. An empty list is a valid discovery result after notebook existence/readability is verified, but cannot authorize restart. The upstream remains authoritative if permissions change between discovery and PUT.

### D2. A one-query WebSocket connection, authenticated by the existing session

The gateway's discovery sequence is:

```text
get_interpreter_bindings(notebook_id)
  -> serialize this discovery within the plugin process
  -> existing lazy session login, if credentials are configured
  -> GET {REST base}/notebook/{encoded notebook_id} (no reload)
  -> verify OK body object with matching id; discard notebook content
  -> GET {REST base}/security/ticket using the same session
  -> validate transient ticket metadata
  -> connect to the derived /ws with same-origin session cookies
  -> send GET_INTERPRETER_BINDINGS for this notebook
  -> accept INTERPRETER_BINDINGS on this connection
  -> close socket, erase transient ticket references
  -> return sanitized bindings; service adds restart_allowed
```

The notebook GET is required because the WebSocket query alone does not provide a reliable not-found distinction or a separate read-permission check. It may fetch paragraph data internally; never expose or log that content, and apply the existing response byte ceiling while reading. A notebook exceeding the configured ceiling fails closed rather than bypassing the check. This extra read is deliberate and task-scoped.

Use `GET /security/ticket` after ordinary session login rather than relying on the login response shape. Preserve the server-provided `roles` string after confirming it decodes to a string array; never accept ticket/principal/roles from MCP input or config. Bound each private string and the complete HTTP response by `max_response_bytes`. Reject malformed metadata, redirects, and authentication challenges safely. With no configured login pair, retain the existing anonymous HTTP mode and proceed only if the upstream issues an anonymous ticket and permits the notebook query; do not fabricate one. This does not promise anonymous access on deployments that disable it.

One fresh socket handles exactly one query. The upstream does not reliably echo a correlation ID, so never multiplex notebooks over one socket or require a nonexistent response `noteId`. Include a random request `msgId` for compatibility but correlate the response by the isolated connection and expected op. Serialize discovery calls through an async lock, including ticket acquisition; lock waiting counts against the call deadline. A cancelled waiter must not cancel the active caller. Notebook-mode restart may query and then PUT without taking the discovery lock recursively.

The WebSocket helper accepts only the internally derived URL and credentials. HTTP cookie selection must respect origin, cookie domain/path, expiry and Secure attributes; construct selection for the corresponding HTTP(S) `/ws` URL before switching its scheme. Do not forward arbitrary headers, cookies to a redirected host, or authentication to environment proxies. Preserve TLS verification. Reject WebSocket redirect responses rather than following them with credentials.

`base_url` remains the existing REST base (examples use `/api`). For discovery, require its normalized path to end with a literal `/api`; replace only that suffix with `/ws` and map `http -> ws`, `https -> wss`. Preserve host, port and earlier proxy path. If the suffix is absent, discovery/notebook-mode restart returns a safe `CONFIG_ERROR` before login/network; other existing tools and legacy restart keep their existing behavior. This fail-closed rule avoids guessing how custom REST mounts map to WebSocket mounts. There is no new URL override field.

### D3. Bounded asynchronous transport and secret handling

Add `websockets>=15,<16` as a direct runtime dependency: `httpx` provides no WebSocket client, and [websockets 15's asyncio client](https://websockets.readthedocs.io/en/15.0/reference/asyncio/client.html) supports Python 3.10, TLS, headers, message ceilings and bounded connection closure. Use its context-managed single connection, not its reconnect iterator. Keep `proxy=None`, `compression=None`, `max_queue=1`, `max_size=max_response_bytes`, and disable library wire/payload logging through a plugin-private logger that emits no transport records even under application debug mode. Do not copy the frontend's logging of tickets and full messages.

`request_timeout_seconds` is one wall-clock work budget for each new discovery or notebook-mode restart call, including lock waiting, login, HTTP reads, ticket, socket setup, receives, and the PUT. Use Python-3.10-compatible deadline calculations and `asyncio.wait_for` with remaining budget; do not reset the deadline for each frame or use Python-3.11-only `asyncio.timeout`. Cleanup gets at most `min(5, request_timeout_seconds)` additional seconds; after that abort the underlying socket transport. Built-in HTTPX/WebSocket connections and receive tasks must not outlive cleanup or shutdown. Unused HTTP response streams are closed; the shared HTTP client remains process-owned and closes on shutdown.

Python cannot forcibly terminate an arbitrary injected coroutine that ignores cancellation after its transport abort hook raises or returns without releasing it. At that test/custom-transport boundary, invoke abort within the cleanup allowance, keep a strong reference to the pending send task, consume its eventual outcome silently, release the discovery lock, and let caller cancellation or process shutdown finish. This is a defensive ownership escape hatch for a broken injection seam, not permission for the built-in HTTPX/WebSocket paths to leave sockets or receive work behind.

For each query, count every received application message's UTF-8 bytes toward a cumulative `max_response_bytes` ceiling and accept at most 32 messages (including unrelated ops and the final response). `max_size` also bounds one incoming message. Ignore only well-formed, non-error JSON envelopes with other string ops, within these limits. `SESSION_LOGOUT`/`AUTH_INFO` fail authentication; `ERROR_INFO` fails upstream without copying its text. Binary frames, invalid JSON/envelopes, malformed expected payloads, duplicate setting IDs, or exhausted frame/byte limits fail with `UNEXPECTED_RESPONSE`. Silence reaches the fixed deadline. No automatic reconnect, login retry, or restart retry is performed.

Allow at most 256 bindings and 64 interpreter names per binding, with non-empty names bounded to 256 characters and no control characters. Empty `interpreters` arrays are valid. Every selected flag must be a strict boolean. Reject malformed entries instead of skipping them; silently returning a partial set could select the wrong target. Ignore and discard extra upstream fields. The complete public discovery JSON, serialized compactly as UTF-8 with `ensure_ascii=False`, must fit `max_result_bytes`; fail if it does not fit, rather than truncate IDs or selections. These collection ceilings are fixed protocol limits, not new settings.

Transient ticket values, roles and cookies stay exclusively in adapter memory, with non-repr secret containers; clear references after the query. Exceptions must be converted without raw message/traceback logging. Sanitized public string fields must also be checked for configured secrets and transient ticket/cookie values; a tainted field makes the call fail safely instead of returning the value. Tests inject recognizable fake secrets into success and error payloads and enable debug logging. Do not store live responses as fixtures.

### D4. Public contracts

All result models are immutable, strictly typed, reject extra public fields, and contain no transport objects. Existing tools other than restart are unchanged.

#### `get_interpreter_bindings`

| Input | Type | Required | Validation |
|---|---|---|---|
| `notebook_id` | string | yes | Non-empty, no control characters, length <= `max_opaque_id_chars`; preserve opaque text. |

`InterpreterBindingsResult` example (synthetic):

```json
{
  "notebook_id": "note-example",
  "bindings": [
    {"setting_id":"spark_prod","name":"spark_prod","interpreters":["spark","sql","pyspark"],"selected":true,"restart_allowed":true},
    {"setting_id":"sh","name":"sh","interpreters":["sh","terminal"],"selected":true,"restart_allowed":false}
  ]
}
```

`bindings` items are `InterpreterBinding` with exactly `setting_id`, `name`, `interpreters`, `selected`, `restart_allowed`; `interpreters` is an array of the upstream sub-interpreter names, not fabricated magic strings. Public `notebook_id` is the validated caller value. No `group`, `status`, class name, properties, ACL list, ticket or dependencies are returned. A readable notebook with no entries yields `{"notebook_id":"note-example","bindings":[]}`.

#### `restart_interpreter`

| Input | Type | Required | Validation |
|---|---|---|---|
| `setting_id` | string | yes | Same bounded opaque-ID rule, exact local allowlist membership; no trimming, case folding or name/group substitution. |
| `notebook_id` | string or null | no, default null | When present: bounded opaque ID plus successful discovery and selected binding membership before the PUT. |

Keep `RestartInterpreterResult` exactly as before:

```json
{"setting_id":"spark_prod","name":"spark_prod","group":"spark","status":"READY"}
```

This acknowledges the server's reported setting state; it does not establish a successful Spark job, completed recovery, or isolated effect. Require the response ID to equal the requested ID and all four fields to be actual non-empty bounded strings (names/group/status <=256 characters, no controls), discarding all extra upstream data. Missing fields or a mismatched ID fail with `UNEXPECTED_RESPONSE`; the tool never repeats the PUT to repair an uncertain outcome. Check complete restart result bytes against `max_result_bytes` too.

#### Gateway and private transport interfaces

| Interface | Inputs | Output |
|---|---|---|
| Gateway `get_interpreter_bindings` | Validated `notebook_id: str` | Immutable tuple of sanitized upstream binding records (`setting_id`, `name`, `interpreters`, `selected`); service decorates local policy. |
| Gateway `restart_interpreter` | Validated `setting_id: str`, `notebook_id: str | None = None` | Existing four-field `RestartInterpreterResult`. |
| Proposed private WebSocket helper `query_bindings` | Derived `url: str`; private session/ticket context; `notebook_id: str`; deadline and configured byte limit | Same sanitized binding records as gateway; no raw envelope or auth fields cross into service. |
| Gateway/runtime `close` | No arguments | Async completion with no result; idempotently terminates active discovery and closes clients. |

Gateway/helper record JSON illustration: `[{"setting_id":"spark_prod","name":"spark_prod","interpreters":["spark","sql"],"selected":true}]`. `close` has no JSON payload (`null` if represented). Internal names are proposed implementation interfaces, not existing upstream APIs.

#### Upstream request/response shapes

All REST paths below are relative to configured REST base; see the source table above for each endpoint/entity.

| Operation | Inputs | Bounded response used |
|---|---|---|
| Existing `POST /login` | Environment-resolved `userName`, `password`, form encoded with correct escaping | Existing session-cookie handling; do not expose response. |
| `GET /notebook/{id}` | Encoded notebook path ID; existing session | `{"status":"OK","body":{"id":"note-example"}}` (other notebook fields discarded). |
| `GET /security/ticket` | Existing session; no tool-supplied authentication | `{"status":"OK","body":{"principal":"<redacted>","ticket":"<redacted>","roles":"[]"}}` (shape illustration only). |
| WebSocket `/ws` | Session-authenticated handshake, one query envelope shown below | `INTERPRETER_BINDINGS` envelope shown below. |
| `PUT /interpreter/setting/restart/{id}` | Encoded setting ID; notebook JSON below or no body for legacy mode | `{"status":"OK","body":{"id":"spark_prod","name":"spark_prod","group":"spark","status":"READY"}}`. |

WebSocket request (authentication placeholders are documentary, never callable MCP fields):

```json
{"op":"GET_INTERPRETER_BINDINGS","data":{"noteId":"note-example"},"principal":"<redacted>","ticket":"<redacted>","roles":"[]","msgId":"query-example-1"}
```

Expected server reply, without requiring a correlation echo:

```json
{"op":"INTERPRETER_BINDINGS","data":{"interpreterBindings":[{"id":"spark_prod","name":"spark_prod","interpreters":[{"name":"spark"},{"name":"sql"}],"selected":true}]}}
```

Notebook-mode restart body: `{"noteId":"note-example"}`. Notebook ID is JSON data, not interpolated into a WebSocket URL. All REST ID segments are encoded exactly once with no safe characters. The new raw-ID acceptance includes numeric-leading and reserved characters as data; no upstream ID/name format is inferred from paragraph interpreter syntax.

### D5. Configuration and examples

No new configuration keys. This is the complete resulting Zeppelin settings table; unchanged defaults are retained. Collections in environment overrides use JSON arrays, matching the current loader (older restart prose describing comma-separated lists is corrected here).

| Field | Type | Default | Range | Required |
|---|---|---|---|---|
| `base_url` | string | none | Absolute HTTP(S), no userinfo/query/fragment, trailing slash removed; discovery requires terminal `/api` | yes |
| `request_timeout_seconds` | number | 30 | >0 and <=300 seconds | no |
| `max_response_bytes` | integer | 1048576 | 1..8388608 | no |
| `max_result_bytes` | integer | 65536 | 1..1048576 | no |
| `max_notebook_name_chars` | integer | 256 | 1..1024 | no |
| `max_paragraph_title_chars` | integer | 256 | 1..1024 | no |
| `max_paragraph_body_bytes` | integer | 65536 | 1..1048576 | no |
| `max_opaque_id_chars` | integer | 512 | 1..4096 | no |
| `allowed_interpreters` | string array | `[]` | Unique, case-sensitive, each `[A-Za-z][A-Za-z0-9_.-]{0,63}` | no |
| `sql_write_allowed_databases` | string array | `["tmp_dc_ep"]` | Unique identifiers `[A-Za-z_][A-Za-z0-9_]*` | no |
| `sql_forbidden_keywords` | string array | `["DROP","TRUNCATE"]` | Uppercased unique `[A-Z][A-Z_]*` | no |
| `sh_allowed_commands` | string array | `[]` | Unique safe command names using existing interpreter-name syntax | no |
| `restartable_interpreter_settings` | string array | `[]` | Unique case-sensitive non-empty opaque IDs <= `max_opaque_id_chars`, no control characters, no coercion of numbers to strings | no |

`restartable_interpreter_settings` requires cross-field validation against `max_opaque_id_chars`; changing the interpreter-name regex globally is not acceptable because paragraph and command validation have different contracts. Preserve spaces/reserved characters in IDs as data and encode at the REST boundary. Public error identifiers longer than the core's 256-character limit are omitted, never truncated into a different ID.

| Configuration envelope/secret field | Type | Default | Range | Required |
|---|---|---|---|---|
| `version` | integer | 1 for env-only synthesis | exactly 1 | yes in file |
| `plugin` | string | selected CLI plugin in env-only mode | exactly `zeppelin` | yes in file |
| `settings` | object | synthesized for env-only mode | only table fields above | yes in file |
| `secrets` | object | `{}` in env-only mode | only username/password references | yes in file |
| `secrets.username` | env-variable-name string | absent | valid existing variable name, paired with password | no |
| `secrets.password` | env-variable-name string | absent | valid existing variable name, paired with username | no |

Proposed file `docs/examples/zeppelin.yaml` (the JSON equivalent will be added during implementation):

```yaml
version: 1
plugin: zeppelin
settings:
  # Existing REST API base; /zeppelin is an illustrative reverse-proxy prefix.
  base_url: https://zeppelin.example.invalid/zeppelin/api
  request_timeout_seconds: 30
  # Paragraph execution permission and restart permission remain independent.
  allowed_interpreters: [spark_prod.sql]
  restartable_interpreter_settings: [spark_prod]
secrets:
  # Values below are environment variable names, never credentials.
  username: ZEPPELIN_USERNAME
  password: ZEPPELIN_PASSWORD
```

With the two credentials already supplied by the launching environment:

```sh
uv run --locked mcp-stdio --plugin zeppelin --config docs/examples/zeppelin.yaml
```

Environment-only equivalent (credentials still supplied externally, not written into shell history):

```sh
export ZEPPELIN_BASE_URL='https://zeppelin.example.invalid/zeppelin/api'
export ZEPPELIN_REQUEST_TIMEOUT_SECONDS='30'
export ZEPPELIN_ALLOWED_INTERPRETERS='["spark_prod.sql"]'
export ZEPPELIN_RESTARTABLE_INTERPRETER_SETTINGS='["spark_prod"]'
uv run --locked mcp-stdio --plugin zeppelin
```

| Variable | Mapping |
|---|---|
| `ZEPPELIN_BASE_URL` | `settings.base_url` |
| `ZEPPELIN_REQUEST_TIMEOUT_SECONDS` | `settings.request_timeout_seconds` |
| `ZEPPELIN_MAX_RESPONSE_BYTES` | `settings.max_response_bytes` |
| `ZEPPELIN_MAX_RESULT_BYTES` | `settings.max_result_bytes` |
| `ZEPPELIN_MAX_NOTEBOOK_NAME_CHARS` | `settings.max_notebook_name_chars` |
| `ZEPPELIN_MAX_PARAGRAPH_TITLE_CHARS` | `settings.max_paragraph_title_chars` |
| `ZEPPELIN_MAX_PARAGRAPH_BODY_BYTES` | `settings.max_paragraph_body_bytes` |
| `ZEPPELIN_MAX_OPAQUE_ID_CHARS` | `settings.max_opaque_id_chars` |
| `ZEPPELIN_ALLOWED_INTERPRETERS` | `settings.allowed_interpreters`, JSON array |
| `ZEPPELIN_SQL_WRITE_ALLOWED_DATABASES` | `settings.sql_write_allowed_databases`, JSON array |
| `ZEPPELIN_SQL_FORBIDDEN_KEYWORDS` | `settings.sql_forbidden_keywords`, JSON array |
| `ZEPPELIN_SH_ALLOWED_COMMANDS` | `settings.sh_allowed_commands`, JSON array |
| `ZEPPELIN_RESTARTABLE_INTERPRETER_SETTINGS` | `settings.restartable_interpreter_settings`, JSON array |
| `ZEPPELIN_USERNAME` / `ZEPPELIN_PASSWORD` | Resolved credentials, supplied by the process environment |

Existing precedence remains plugin-prefixed environment override, generic `MCP_STDIO__SETTINGS__<FIELD>` override, file/default. Startup validates locally without resolving a ticket or opening HTTP/WebSocket connections. A host entry continues to launch one `mcp-stdio --plugin zeppelin` child and forward the needed environment variable names; there is no new host transport configuration.

### D6. Architecture and error mapping

Keep domain records in `models.py` and the port in `gateway.py`; neither imports HTTP/WebSocket/MCP libraries. Service handles validation, allowlist, binding membership and local-policy decoration. Existing `http_client.py` remains the gateway implementation and owns session acquisition, HTTP responses, and composition of a small plugin-local `websocket_client.py` helper. The helper owns frame encoding/parsing and socket lifecycle, with an injected connector seam for deterministic fakes. `plugin.py` composes the service and gateway. Add architecture test rules forbidding services from importing `websockets` or `websocket_client`.

The core receives only `GET_INTERPRETER_BINDINGS` and its `{notebook_id}` safe identifier mapping; restart permits `{setting_id, notebook_id}`. Every failure during notebook-mode restart reports operation `restart_interpreter`, even if it originated in login/discovery. Do not leave the current login helper's hard-coded `create_notebook` attribution on these new paths. Preserve existing mappings for unrelated tools and legacy restart.

| Failure | New discovery / notebook-mode restart category | Retryable |
|---|---|---|
| Invalid input, not allowlisted, or absent/unselected setting after discovery | `INVALID_INPUT` | false |
| REST base cannot derive `/ws` | `CONFIG_ERROR` | false |
| HTTP/handshake 401; missing/invalid session, `SESSION_LOGOUT`, `AUTH_INFO` | `AUTHENTICATION_FAILED` | false |
| HTTP/handshake 403 | `PERMISSION_DENIED` | false |
| Notebook precheck HTTP 404 | `NOT_FOUND` | false |
| WebSocket route unavailable (404), other HTTP/handshake errors, `ERROR_INFO`, restart 404/500 | `UPSTREAM_ERROR` | false |
| Bad envelope/types, oversized response, duplicate IDs, mismatched result ID, limits exhausted | `UNEXPECTED_RESPONSE` | false |
| Deadline expires | `TIMEOUT` | true for discovery; false for restart |
| Connection cannot open or closes before the expected response | `CONNECTION_FAILED` | true for discovery; false for restart |
| Caller cancellation or process shutdown | Propagate cancellation after bounded cleanup; no fabricated successful result | n/a |

Notebook-mode restart is never labelled automatically retryable, because a transport error can follow an already processed PUT. It makes no repeat PUT. Legacy mode retains its existing categories/retryable flags for compatibility, with documentation prohibiting automatic retries in either mode.

Example public error (`ToolError`, illustrative correlation ID):

```json
{"category":"INVALID_INPUT","operation":"restart_interpreter","message":"The request input is invalid.","retryable":false,"identifiers":{"setting_id":"spark_prod","notebook_id":"note-example"},"correlation_id":"00000000-0000-4000-8000-000000000000","explanation":"The setting is not a selected binding for this notebook."}
```

Use fixed explanations, omit unsafe/overlong identifiers, and never pass raw upstream text to the error serializer. The new helper must remain silent on stdout and must not log headers, message bodies, or exception representations on stderr, including while closing clients.

## Risks / Trade-offs

- **Shared interpreter process** -> notebook context does not guarantee isolation. Document the scope and leave upstream permission checks authoritative; no automatic paragraph retry.
- **WebSocket routes/proxy settings differ** -> derive only the documented `/api` to `/ws` mapping, fail clearly when unavailable, and never fall back to an admin endpoint or setting-wide restart.
- **Undocumented WebSocket schema/version differences** -> pin evidence to 0.10.1, parse only verified fields, fail closed, and validate on an explicitly configured non-admin test deployment. Unknown variants require updating the artifacts first.
- **Notebook precheck may be large** -> enforce response bounds and discard content; exceeding the cap is a clear error, not an empty binding list.
- **No correlation echo and mutable sessions** -> isolate one query per socket and serialize discovery; reread bindings for notebook-mode restart. Race conditions after the check remain an upstream concern.
- **Ticket material and library debug output** -> use private non-repr values, suppress wire logs, sanitize public fields, and test stdout/stderr under debug with fake secret sentinels.
- **Compatibility keeps global restart available** -> distinguish omitted/null notebook context explicitly in the schema/description and Agent skill; never remove context as an error recovery strategy.

## Migration Plan

1. Implement in `tasks.md` order, with shared contracts and adapter behavior settled serially before tool wiring. Resolve the new direct dependency with uv and commit the lockfile during implementation.
2. Upgrade the package and refresh MCP tool discovery; add no mandatory configuration keys. Existing restart clients keep working. Operators can reuse current explicit allowlist IDs or copy IDs from the new query.
3. Update README, examples, architecture views, and the canonical Zeppelin skill together. No automatic edits to users' installed copies, host configuration, allowlists or deployment authorization.
4. Run opt-in read-only discovery against an ordinary account when credentials are provided. A live restart requires a separate explicit integration opt-in and a dedicated test setting/notebook; never use the user's working notebook as a test target by default.
5. Roll back by restoring the prior package/lockfile and the matching skill. No Zeppelin resources or server configuration are migrated. New callers must stop using the new tool/parameter after rollback; old restrictive ID validation may reject newly configured opaque IDs.

### Proposal validation baseline (2026-09-10)

- `openspec validate support-zeppelin-notebook-interpreter-restart --strict`: passed. The CLI also reports that this MODIFIED delta cannot be archived until the predecessor Zeppelin capability has been created in main specs; the archive ordering above addresses that dependency.
- `openspec validate --changes --strict`: 13 passed, 0 failed. Existing unarchived capabilities produce informational archive-order notices.
- `openspec validate --specs --strict`: 0 passed, 2 failed. Both `hive-schema-tools` and `plugin-stdio-runtime` have placeholder Purpose text. The same text is present in `HEAD` before this proposal; neither main spec was changed here.
- These baseline failures do not prevent the new planning artifacts from being apply-ready, but they must be resolved as an explicit documentation prerequisite before the final whole-change verification can be marked passed. Task 7.1 must not waive or conceal them.
- No implementation tests or live integration tests were run for this documentation-only proposal. All implementation tasks remain unchecked.
