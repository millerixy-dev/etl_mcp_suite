## MODIFIED Requirements

### Requirement: Expose exactly the Zeppelin notebook lifecycle tools
The Zeppelin plugin SHALL expose exactly `list_notebooks`, `create_notebook`, `add_paragraph`, `run_paragraph`, `get_paragraph_status`, `get_paragraph_result`, `restart_interpreter`, `cancel_paragraph`, and `get_interpreter_bindings`. Existing tool schemas SHALL remain unchanged except for the additive optional `notebook_id` on restart and the corrected setting-ID validation.

#### Scenario: List Zeppelin tools
- **GIVEN** a configured Zeppelin plugin process
- **WHEN** an MCP client lists tools
- **THEN** exactly the nine named tools are present, and listing tools opens no upstream connection

### Requirement: Validate a fixed Zeppelin V1 configuration
The Zeppelin plugin SHALL accept only these non-sensitive settings: `base_url`, `request_timeout_seconds`, `max_response_bytes`, `max_result_bytes`, `max_notebook_name_chars`, `max_paragraph_title_chars`, `max_paragraph_body_bytes`, `max_opaque_id_chars`, `allowed_interpreters`, `sql_write_allowed_databases`, `sql_forbidden_keywords`, `sh_allowed_commands`, and `restartable_interpreter_settings`. `base_url` MUST be an absolute HTTP or HTTPS URL without user information, query, or fragment; it MAY include a reverse-proxy path and SHALL be normalized without a trailing slash. Numeric settings SHALL use strict numeric types and these ranges/defaults: timeout >0 and <=300 seconds (default 30); response bytes 1..8388608 (default 1048576); result bytes 1..1048576 (default 65536); notebook and paragraph-title characters 1..1024 (default 256 each); paragraph-body bytes 1..1048576 (default 65536); opaque-ID characters 1..4096 (default 512).

`allowed_interpreters` SHALL default to an immutable empty sequence; entries MUST match `[A-Za-z][A-Za-z0-9_.-]{0,63}` and be unique and case-sensitive. `sql_write_allowed_databases` SHALL retain default `["tmp_dc_ep"]` and unique `[A-Za-z_][A-Za-z0-9_]*` identifiers. `sh_allowed_commands` SHALL retain default empty and unique safe names using the interpreter-name syntax. `sql_forbidden_keywords` SHALL default to `["DROP","TRUNCATE"]`; entries SHALL normalize to uppercase, match `[A-Z][A-Z_]*`, and reject duplicates after normalization. Their enforcement remains case-insensitive.

`restartable_interpreter_settings` SHALL default to an immutable empty sequence and contain unique, case-sensitive, non-empty string IDs, bounded by `max_opaque_id_chars` and containing no control characters. IDs SHALL be preserved exactly, including numeric-leading and URL-reserved syntax as data; they MUST NOT be treated as interpreter names or groups. Numeric/boolean entries SHALL NOT be coerced into strings. The configuration SHALL reject unknown fields, unsupported versions, plugin mismatches and invalid types. No ticket, cookie, roles, WebSocket URL or caller-authentication setting SHALL be introduced.

Environment collection overrides SHALL use JSON arrays, matching the existing loader. Plugin-prefixed variables SHALL override generic setting overrides and file values; environment-only startup SHALL remain supported. Startup validation SHALL be local and SHALL NOT obtain a ticket or connect to an upstream service.

#### Scenario: Load equivalent Zeppelin settings
- **GIVEN** equivalent version 1 YAML and JSON files
- **WHEN** configuration is loaded
- **THEN** the resulting settings are equivalent and no network request occurs

#### Scenario: Default to deny
- **GIVEN** `allowed_interpreters` is omitted
- **WHEN** configuration is loaded
- **THEN** the execution allowlist is empty

#### Scenario: Default forbidden keywords
- **GIVEN** `sql_forbidden_keywords` is omitted
- **WHEN** configuration is loaded
- **THEN** the value is `["DROP","TRUNCATE"]`

#### Scenario: Override forbidden keywords from the environment
- **GIVEN** file defaults and `ZEPPELIN_SQL_FORBIDDEN_KEYWORDS` containing a JSON array of keywords
- **WHEN** configuration is loaded
- **THEN** the environment array takes precedence and entries are normalized to uppercase

#### Scenario: Default restartable interpreter settings to deny
- **GIVEN** `restartable_interpreter_settings` is omitted
- **WHEN** configuration is loaded
- **THEN** the restart allowlist is empty and no setting is locally permitted to restart

#### Scenario: Override restartable interpreter settings from the environment
- **GIVEN** `ZEPPELIN_RESTARTABLE_INTERPRETER_SETTINGS='["spark_prod","2AY6GV7Q3"]'` and a different file value
- **WHEN** configuration is loaded
- **THEN** those two exact string IDs replace the file value

#### Scenario: Bound restart IDs independently from interpreter names
- **GIVEN** an opaque setting ID starts with a digit or includes URL-reserved syntax and fits `max_opaque_id_chars`
- **WHEN** the ID is configured in the restart allowlist
- **THEN** it is preserved as data while paragraph interpreter-name validation retains its existing syntax

#### Scenario: Reject unsafe configuration
- **GIVEN** a credential-bearing or malformed URL, out-of-range limit, duplicate entry, invalid type, invalid secret reference, malformed interpreter/keyword, overlong or control-containing restart ID, or unknown field
- **WHEN** configuration is loaded
- **THEN** it fails with safe `CONFIG_ERROR` without echoing the rejected value or making a request

#### Scenario: Do not coerce a numeric restart ID
- **GIVEN** the restart allowlist contains JSON number `123` rather than string `"123"`
- **WHEN** configuration is loaded
- **THEN** it fails with safe `CONFIG_ERROR`

### Requirement: Restart an allowlisted interpreter setting
The `restart_interpreter` tool SHALL accept required `setting_id` and optional nullable `notebook_id` defaulting to null. Both non-null IDs MUST be non-empty strings, fit `max_opaque_id_chars`, contain no control characters and be preserved without normalization. Before any network access, invalid inputs and setting IDs absent from `restartable_interpreter_settings` SHALL produce `INVALID_INPUT`. Setting IDs are upstream IDs, not group names inferred from paragraph text.

When `notebook_id` is absent or null, restart SHALL preserve the existing explicit setting-wide `PUT /api/interpreter/setting/restart/{setting_id}` with no notebook request body and no binding-discovery dependency. When `notebook_id` is present, the tool SHALL establish notebook readability/existence, query current interpreter bindings, and require an exact selected binding ID before sending exactly one PUT with JSON `{"noteId": notebook_id}`. Query errors or missing/unselected membership SHALL prevent that PUT; membership failure SHALL return `INVALID_INPUT`. The setting ID SHALL be encoded once as one REST URL path segment. Notebook ID SHALL remain JSON data in the restart body.

The tool SHALL return `RestartInterpreterResult` with exactly `setting_id`, `name`, `group`, and `status`. These MUST be actual non-empty control-free strings; `setting_id` MUST fit `max_opaque_id_chars` and equal the requested ID, and the other fields MUST be at most 256 characters. The complete compact UTF-8 result MUST fit `max_result_bytes`. Extra upstream properties, dependencies, stack traces, options and interpreter groups SHALL be discarded. A missing/malformed field, mismatched ID or oversized result SHALL return `UNEXPECTED_RESPONSE` without repeating the PUT. A successful response acknowledges the server's reported state and SHALL NOT claim isolated impact, successful paragraph execution, or a verified healthy Spark session.

Notebook-mode failures SHALL follow the discovery error contract below, attributed to `restart_interpreter`; restart endpoint 404/500 and other non-authentication HTTP errors SHALL be `UPSTREAM_ERROR`. All notebook-mode restart errors SHALL set `retryable=false`. Legacy setting-only HTTP mappings SHALL remain compatible: 401/403 map to `AUTHENTICATION_FAILED`, other >=400 responses to `UPSTREAM_ERROR`, transport timeout to `TIMEOUT`, and connection failure to `CONNECTION_FAILED`, with existing retryability metadata. Neither mode SHALL automatically retry a PUT, reconnect as a restart retry, run a paragraph, or remove notebook context to recover from an error.

The authentication envelope SHALL be released after the binding query. A contextual restart MAY retain only the query-scoped fail-closed secret guard through PUT result validation and SHALL clear it on every operation outcome; it SHALL NOT cache ticket or guard state across calls. Every public restart string in either mode SHALL reject available configured/session secret values, including response-installed session cookies. Contextual restart SHALL additionally reject its query-scoped principal, ticket, decoded role and cookie values.

The shared logging policy SHALL suppress `httpx` and `httpcore` transport logs, including child loggers, before application startup requests or adapter-owned HTTP client use. Suppression SHALL prevent transport debug representation creation, preserve the root logger and redacting application stderr logger, and SHALL NOT attach transient authentication values to global logging state.

#### Scenario: Supported startup does not emit transport authentication material
- **GIVEN** FastMCP startup enables root INFO logging or external logging enables root DEBUG and an HTTP transport would log a request URL, header or exception containing a synthetic secret
- **WHEN** the Zeppelin adapter performs a restart with its owned client
- **THEN** no `httpx` or `httpcore` record or transport debug representation is emitted, application safe diagnostics remain available, and unrelated root logging is unchanged

#### Scenario: Failed authentication or requests omit available session secrets
- **GIVEN** configured credentials or cookies installed before or by a login, notebook precheck, ticket or restart response match a public error identifier
- **WHEN** discovery or either restart mode fails during that stage, including failed HTTP status or a response-stream timeout
- **THEN** those identifiers are omitted without extra requests or retry, the operation/category/retryability remain appropriate to the original mode and failure, and no secret is emitted through errors or logging

#### Scenario: Discovery does not echo a tainted notebook identifier
- **GIVEN** a readable notebook ID contains an available configured/session or query-scoped principal, ticket or decoded role secret
- **WHEN** discovery has acquired its private authentication context
- **THEN** it fails closed with secret-safe `UNEXPECTED_RESPONSE` rather than returning `InterpreterBindingsResult` with the tainted `notebook_id`, releases the query context, and does not send a binding query

#### Scenario: Tainted restart success fields fail safely
- **GIVEN** a legacy or contextual restart PUT returns a success body containing an available configured or session secret in a public string, or a contextual success body contains a query-scoped principal, ticket, decoded role or cookie value
- **WHEN** the four-field restart result is validated
- **THEN** no `RestartInterpreterResult` is returned, a secret-safe `UNEXPECTED_RESPONSE` reports `restart_interpreter` with safe identifiers and `retryable=false`, exactly one PUT was sent, and there is no retry or context-dropping fallback
- **AND** the call-local guard is released without emitting secret values to stdout, stderr, logs or public results

#### Scenario: Restart an allowlisted interpreter
- **GIVEN** `spark` is allowlisted and no notebook context is supplied
- **WHEN** `restart_interpreter(setting_id="spark")` succeeds upstream
- **THEN** the existing setting-wide PUT is sent without discovery and returns the four-field `RestartInterpreterResult`

#### Scenario: Explicit null preserves compatibility
- **GIVEN** `spark` is allowlisted
- **WHEN** restart is called with `notebook_id=null`
- **THEN** it behaves identically to omitting `notebook_id`

#### Scenario: Restart using a discovered notebook setting
- **GIVEN** a readable notebook currently returns selected binding ID `spark_prod` and that ID is locally allowlisted
- **WHEN** restart is called with that notebook ID and `setting_id="spark_prod"`
- **THEN** one PUT targets `spark_prod` with the exact notebook `noteId`, returning `RestartInterpreterResult`

#### Scenario: Reject a non-allowlisted interpreter before network
- **GIVEN** the restart allowlist is empty, even if the setting exists upstream
- **WHEN** restart is requested with or without notebook context
- **THEN** safe `INVALID_INPUT` is returned before login, HTTP, ticket or WebSocket access

#### Scenario: Reject malformed inputs before network
- **GIVEN** an empty, non-string, overlong or control-containing setting ID or a non-null notebook ID with those defects
- **WHEN** restart is called
- **THEN** it returns safe `INVALID_INPUT` without network access, and an empty notebook ID never selects setting-wide mode

#### Scenario: Encode an opaque setting ID
- **GIVEN** a bounded, allowlisted setting ID contains numeric-leading or URL-reserved syntax
- **WHEN** restart is called
- **THEN** the same ID is checked without normalization and encoded as a single path segment without altering the target endpoint

#### Scenario: Reject absent or unselected membership
- **GIVEN** the allowlisted ID is absent from current bindings, present with `selected=false`, or the valid binding list is empty
- **WHEN** notebook-mode restart is requested
- **THEN** safe `INVALID_INPUT` is returned and no restart PUT occurs

#### Scenario: Do not fall back after discovery failure
- **GIVEN** the notebook query fails with denied access, missing notebook, timeout, unavailable WebSocket or malformed response
- **WHEN** notebook-mode restart is requested
- **THEN** the appropriate safe error names operation `restart_interpreter`, sets `retryable=false`, and neither a contextual nor a setting-wide restart is sent

#### Scenario: Report upstream failure for nonexistent setting
- **GIVEN** an allowlisted setting is absent upstream and Zeppelin returns HTTP 500 to the PUT
- **WHEN** restart is requested
- **THEN** `UPSTREAM_ERROR` is returned with only safely representable identifiers

#### Scenario: Do not repeat an uncertain restart
- **GIVEN** the PUT was sent but its response times out or reports the wrong setting ID
- **WHEN** the call terminates
- **THEN** it returns respectively `TIMEOUT` or `UNEXPECTED_RESPONSE`, sends no second PUT, and notebook mode has `retryable=false`

#### Scenario: Result omits raw properties and dependencies
- **GIVEN** a successful upstream restart response contains extra properties, options and dependencies
- **WHEN** it is normalized
- **THEN** `RestartInterpreterResult` contains only its four declared fields

## ADDED Requirements

### Requirement: Discover interpreter bindings for a readable notebook
The `get_interpreter_bindings` tool SHALL accept exactly required `notebook_id`, a non-empty control-free opaque string bounded by `max_opaque_id_chars`. Invalid input SHALL fail before network access. Using the same upstream user session, it SHALL verify notebook existence and read access through `GET /api/notebook/{encoded notebook_id}` without reload and require a matching response ID. It SHALL discard notebook content and then use WebSocket `GET_INTERPRETER_BINDINGS` with `data.noteId`; the query SHALL NOT use the admin interpreter-list REST endpoint or change bindings.

Success SHALL return immutable `InterpreterBindingsResult` with exactly `notebook_id` and `bindings`. Each `InterpreterBinding` SHALL contain exactly `setting_id`, `name`, `interpreters`, `selected`, and `restart_allowed`. `setting_id` SHALL be the exact upstream `id`; `name` the setting name; `interpreters` an array of upstream sub-interpreter names; `selected` the exact upstream boolean; and `restart_allowed` the exact local ID allowlist decision. No group or interpreter prefix SHALL be guessed. Local permission SHALL NOT be described as upstream authorization or health.

The tool SHALL preserve binding and sub-interpreter order, include valid locally denied settings, and return an empty `bindings` array only after successful notebook verification and a valid empty upstream response. Missing notebooks and unreadable notebooks SHALL NOT be disguised as empty results. It SHALL permit discovery with an empty restart allowlist and without any paragraph execution allowlist.

#### Scenario: Discover bindings as an ordinary user
- **GIVEN** a non-admin session can read a notebook and use its WebSocket query, while admin REST settings enumeration is denied
- **WHEN** `get_interpreter_bindings` is called
- **THEN** `InterpreterBindingsResult` returns the upstream setting IDs without attempting admin settings enumeration

#### Scenario: Distinguish setting name from group
- **GIVEN** the upstream returns ID/name `spark_prod` and interpreter names `spark`, `sql`
- **WHEN** the response is normalized
- **THEN** `InterpreterBinding.setting_id` is `spark_prod`, `interpreters` is `["spark","sql"]`, and no group is invented

#### Scenario: Discovery does not require restart permission
- **GIVEN** execution and restart allowlists are empty
- **WHEN** a valid bindings response is received for a readable notebook
- **THEN** all valid returned entries remain visible with `restart_allowed=false`, and no restart or paragraph execution is attempted

#### Scenario: Preserve a valid empty binding list
- **GIVEN** notebook verification succeeds and WebSocket returns an empty `interpreterBindings` array
- **WHEN** the tool completes
- **THEN** it returns `InterpreterBindingsResult` with the requested notebook ID and `bindings=[]`

#### Scenario: Fail on unreadable or missing notebook
- **GIVEN** the notebook precheck returns HTTP 403 or 404
- **WHEN** discovery is requested
- **THEN** it returns respectively `PERMISSION_DENIED` or `NOT_FOUND` and does not query bindings

### Requirement: Keep discovery authentication private and reuse the existing session
Discovery SHALL use the existing optional paired environment-backed username/password session mode; absent credentials SHALL leave upstream anonymous access policy authoritative. The tool SHALL obtain fresh ticket metadata using `GET /api/security/ticket` with that session and send the validated server-issued principal, ticket and JSON-array-string roles internally in the WebSocket query envelope. A caller SHALL NOT supply or override those fields through MCP or configuration. Malformed ticket metadata SHALL fail with `UNEXPECTED_RESPONSE`; explicit authentication rejection SHALL fail with `AUTHENTICATION_FAILED`.

The WebSocket URL SHALL be derived from the configured REST `base_url` by replacing only its final `/api` path component with `/ws` and mapping HTTP(S) to WS(S), preserving origin, port and proxy prefix. Discovery and notebook-mode restart SHALL fail with `CONFIG_ERROR` before network access if that mapping cannot be derived; unrelated existing tools SHALL retain their behavior. Authentication SHALL be restricted to the derived origin and valid cookie scope; the transport SHALL NOT forward credentials through redirects or implicit environment proxies or disable TLS verification. Tickets SHALL NOT be persisted or cached between queries.

#### Scenario: Use the session ticket without exposing it
- **GIVEN** the session returns valid private principal, ticket and roles metadata
- **WHEN** a binding query is sent
- **THEN** the transport uses that metadata internally and none appears in MCP schemas, outputs, logs, error representations or committed fixtures

#### Scenario: Reject fabricated or malformed authentication
- **GIVEN** the ticket response is missing a required field or contains roles that are not a JSON-array string of strings
- **WHEN** discovery is requested
- **THEN** it fails with `UNEXPECTED_RESPONSE` and opens no WebSocket connection

#### Scenario: Preserve reverse-proxy paths
- **GIVEN** `base_url` is `https://zeppelin.example.invalid/proxy/api`
- **WHEN** discovery derives the socket URL
- **THEN** it targets `wss://zeppelin.example.invalid/proxy/ws` and retains same-origin authentication

#### Scenario: Reject an ambiguous WebSocket mount
- **GIVEN** the configured REST base has no terminal `/api`
- **WHEN** discovery or notebook-mode restart is requested
- **THEN** it returns `CONFIG_ERROR` before network access and does not guess a URL or switch restart scope

#### Scenario: Refuse authentication forwarding
- **GIVEN** a WebSocket handshake redirects or environment proxy variables are configured
- **WHEN** the query connects
- **THEN** it does not follow the redirect with credentials or use implicit environment proxies

### Requirement: Bound discovery results and connection lifetime
Each query SHALL use one isolated, short-lived WebSocket connection with no multiplexed notebook requests, because the expected reply need not echo a notebook or request identifier. It SHALL accept only a valid `INTERPRETER_BINDINGS` envelope for that isolated query. Discovery SHALL be serialized per plugin process; waiting calls SHALL share neither response state nor tickets and their waiting time SHALL count toward their deadlines.

Each query SHALL enforce `max_response_bytes` for any single message and for cumulative received application-message bytes, a maximum of 32 received application messages including the expected result, and a fixed deadline of `request_timeout_seconds`. Well-formed unrelated non-error envelopes SHALL be ignored only within those bounds. Binary messages, invalid JSON/envelopes or malformed expected payloads SHALL fail with `UNEXPECTED_RESPONSE`.

The public result SHALL have at most 256 bindings, unique setting IDs, at most 64 interpreter names per binding, strict boolean selection, and non-empty control-free setting/interpreter names bounded to 256 characters. An empty interpreter-name array is valid. The entire compact UTF-8 public result SHALL fit `max_result_bytes`; entries, IDs and names SHALL NOT be silently truncated or skipped to make the result fit. Extra upstream fields SHALL be discarded, and a public field containing configured credentials or transient ticket/cookie values SHALL cause a safe failure rather than disclosure.

The deadline for discovery or notebook-mode restart SHALL cover lock waiting and all upstream work in that call, rather than reset for each request or frame. No automatic reconnect or retry SHALL be performed. On success, error, cancellation or shutdown, owned sockets/streams of the built-in HTTPX/WebSocket transports SHALL close within an additional cleanup allowance of at most `min(5, request_timeout_seconds)` seconds; no background receive task SHALL survive cleanup. Process shutdown SHALL close the shared HTTP client and prevent new discovery work. Cleanup SHALL be idempotent and SHALL preserve cancellation. If an injected or custom HTTP transport ignores cancellation of the contextual restart PUT and its abort hook fails or does not release that PUT send task, the adapter SHALL invoke abort within the cleanup allowance, retain and silently observe that task, release the discovery lock, and allow cancellation/shutdown to finish without emitting its eventual outcome; this defensive ownership rule MUST NOT weaken cleanup for the built-in transports or change discovery/precheck cleanup requirements. No new MCP listening socket or non-stdio transport SHALL be created.

#### Scenario: Bound a non-cooperative contextual PUT transport
- **GIVEN** an injected HTTP transport ignores cancellation of the contextual restart PUT and its abort hook raises or does not release that PUT send
- **WHEN** the PUT times out, its caller is cancelled, or process shutdown begins
- **THEN** abort is attempted within the cleanup allowance, the pending task remains strongly owned and silently observed, the discovery lock and caller/shutdown are released within a bounded time, and built-in transport cleanup requirements remain unchanged

#### Scenario: Accept an uncorrelated reply on its isolated connection
- **GIVEN** only this query has used a fresh socket
- **WHEN** a valid `INTERPRETER_BINDINGS` response contains neither `noteId` nor an echoed `msgId`
- **THEN** it is accepted for that query without inventing an upstream correlation requirement

#### Scenario: Isolate concurrent notebook queries
- **GIVEN** two notebook queries overlap
- **WHEN** one is active and the other waits or is cancelled
- **THEN** responses and tickets cannot cross between calls, waiting time is bounded, and cancelling the waiter does not cancel the active query

#### Scenario: Bound unsolicited traffic
- **GIVEN** the server sends unrelated JSON messages before the binding response
- **WHEN** message count, cumulative bytes or the deadline reaches its limit
- **THEN** the query fails with `UNEXPECTED_RESPONSE` for count/bytes or `TIMEOUT` for waiting, closes the connection, and returns no partial result

#### Scenario: Reject malformed or oversized binding results
- **GIVEN** duplicate IDs, missing or coercible fields, invalid names, too many entries, a binary frame or a result exceeding configured byte limits
- **WHEN** discovery processes the response
- **THEN** it returns safe `UNEXPECTED_RESPONSE`, not a truncated or partially accepted `InterpreterBindingsResult`

#### Scenario: Clean up on cancellation and shutdown
- **GIVEN** discovery is waiting for a response or a connection is opening
- **WHEN** the call is cancelled or the plugin shuts down
- **THEN** cleanup finishes within its allowance, active sockets/streams and receive tasks are terminated, cancellation is preserved and no success is fabricated

#### Scenario: Keep debug output secret-safe
- **GIVEN** debug logging is enabled and fake ticket/cookie/credential sentinels appear in incoming fields or transport exceptions
- **WHEN** success parsing or error/cleanup handling runs
- **THEN** no sentinel, raw frame, header, upstream body or exception representation is emitted to stdout, stderr or public results

### Requirement: Report stable discovery failures and document restart scope
Discovery SHALL use the existing `ToolError` result shape and operation `get_interpreter_bindings`. HTTP/handshake 401 and WebSocket `SESSION_LOGOUT` or `AUTH_INFO` SHALL map to `AUTHENTICATION_FAILED`; HTTP/handshake 403 to `PERMISSION_DENIED`; notebook precheck 404 to `NOT_FOUND`; unavailable WebSocket routes, other unsuccessful upstream responses and `ERROR_INFO` to `UPSTREAM_ERROR`; malformed shapes or exceeded content limits to `UNEXPECTED_RESPONSE`; deadline expiry to `TIMEOUT`; and connection failure or premature closure to `CONNECTION_FAILED`. Only discovery timeout/connection failures SHALL be marked retryable; no automatic retry occurs. Errors SHALL contain fixed safe messages and only safe notebook/setting identifiers, omitting identifiers over the core's 256-character limit rather than truncating them.

Tool descriptions, README and the canonical Zeppelin skill SHALL explain discovery followed by explicit selection and notebook-mode restart, independent execution/restart allowlists, optional legacy scope, and shared-process impact. They SHALL forbid guessing IDs, dropping notebook context on failure, treating restart as a general retry, and automatically re-executing paragraphs. Architecture documentation SHALL distinguish local MCP stdio from outgoing Zeppelin HTTP/WebSocket connections.

#### Scenario: Map a WebSocket session failure
- **GIVEN** the server sends `SESSION_LOGOUT` or `AUTH_INFO`
- **WHEN** discovery processes the message
- **THEN** safe non-retryable `AUTHENTICATION_FAILED` is returned without raw server text or ticket values

#### Scenario: Preserve safe attribution for a long identifier
- **GIVEN** a valid notebook ID exceeds the core's error-identifier length limit
- **WHEN** discovery fails
- **THEN** `ToolError.operation` remains `get_interpreter_bindings`, the ID is omitted, and error construction does not itself fail

#### Scenario: Guide recovery without changing restart scope
- **GIVEN** an agent uses the canonical Zeppelin skill after interpreter failure
- **WHEN** it prepares a restart
- **THEN** it is directed to discover and explicitly select the setting with notebook context, respect the allowlist, and avoid automatic paragraph execution or context-dropping fallback
