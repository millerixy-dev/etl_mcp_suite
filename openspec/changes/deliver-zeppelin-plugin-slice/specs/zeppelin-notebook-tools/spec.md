## ADDED Requirements

### Requirement: Validate a fixed Zeppelin V1 configuration
The Zeppelin plugin SHALL accept only these non-sensitive settings: `base_url`, `request_timeout_seconds`, `max_response_bytes`, `max_result_bytes`, `max_notebook_name_chars`, `max_paragraph_title_chars`, `max_paragraph_body_bytes`, `max_opaque_id_chars`, `allowed_interpreters`, `sql_write_allowed_databases`, and `sh_allowed_commands`. `base_url` MUST be an absolute HTTP or HTTPS URL without user information, query, or fragment; it MAY include a reverse-proxy path and SHALL be normalized without a trailing slash. Numeric settings SHALL use strict numeric types and the following inclusive ranges and defaults: timeout greater than zero and at most 300 seconds (default 30), response bytes 1 through 8 MiB (default 1 MiB), result bytes 1 through 1 MiB (default 65,536), notebook and paragraph-title characters 1 through 1,024 (default 256 each), paragraph-body bytes 1 through 1 MiB (default 65,536), and opaque-ID characters 1 through 4,096 (default 512).

`allowed_interpreters` SHALL default to an immutable empty sequence. Each entry MUST match `[A-Za-z][A-Za-z0-9_.-]{0,63}`. Exact duplicate entries are invalid; matching and uniqueness are case-sensitive. The configuration SHALL reject unknown fields and coercion from strings, booleans, or other incompatible scalar types.

#### Scenario: Load equivalent Zeppelin settings
- **WHEN** equivalent valid Zeppelin settings are supplied in version 1 YAML and JSON files
- **THEN** they produce equivalent validated settings without making a network request

#### Scenario: Default to deny
- **WHEN** `allowed_interpreters` is omitted
- **THEN** the validated value is an empty immutable sequence

#### Scenario: Reject unsafe configuration
- **WHEN** a URL contains credentials, query, fragment, or unsupported scheme, a limit is outside its approved range, an interpreter is malformed or duplicated, or an unknown field is present
- **THEN** startup fails with a safe `CONFIG_ERROR` that does not echo the rejected value

### Requirement: Support only optional paired Zeppelin session credentials
The Zeppelin V1 secret schema SHALL contain only optional `username` and `password` environment-backed secret references. Both fields MUST be absent for unauthenticated access or both MUST be present for adapter-managed Zeppelin session login; a partial pair is invalid. An empty `secrets` object is valid. Token, basic-auth, cookie, and caller-supplied authentication modes are not supported in V1.

#### Scenario: Resolve a configured login pair
- **WHEN** both secret fields reference existing environment variables
- **THEN** the resolved values are available only to the adapter and are redacted from representations and validation failures

#### Scenario: Use no authentication
- **WHEN** `secrets` is an empty object
- **THEN** configuration validation succeeds without creating an HTTP client or making a request

#### Scenario: Reject a partial login pair
- **WHEN** only `username` or only `password` is configured
- **THEN** startup fails with a safe `CONFIG_ERROR`

### Requirement: Validate bounded Zeppelin tool inputs without normalization
Notebook names MUST contain at least one non-whitespace character and fit `max_notebook_name_chars`; their original text SHALL be preserved. Paragraph titles MAY be empty and MUST fit `max_paragraph_title_chars`; their original text SHALL be preserved. Paragraph bodies MUST be non-empty and fit `max_paragraph_body_bytes` when encoded as UTF-8. Interpreter names MUST use the configured safe syntax and SHALL later be matched exactly against the case-sensitive allowlist.

Opaque notebook and paragraph IDs MUST be non-empty, fit `max_opaque_id_chars`, and contain no Unicode control character. Other opaque syntax, including slash, traversal, query, and fragment characters, is permitted as data and MUST later be percent-encoded by the adapter as one path segment with no safe characters. Validation failures SHALL use fixed messages and MUST NOT echo rejected input.

#### Scenario: Preserve valid caller text
- **WHEN** a valid notebook name or paragraph title contains leading or trailing whitespace
- **THEN** validation returns the original text unchanged

#### Scenario: Bound UTF-8 paragraph content
- **WHEN** a non-ASCII paragraph body exceeds its configured byte limit after UTF-8 encoding
- **THEN** the request is rejected before any network access

#### Scenario: Preserve opaque syntax for safe encoding
- **WHEN** a bounded opaque ID contains slash, traversal, query, or fragment syntax but no control character
- **THEN** input validation preserves it and path-segment encoding escapes all of that syntax

### Requirement: Use fixed normalized Zeppelin result models
The Zeppelin plugin SHALL use strict immutable JSON-serializable result models with these exact public fields:

- create notebook: `notebook_id`, `name`;
- add paragraph: `notebook_id`, `paragraph_id`, `title`, `interpreter`;
- run acknowledgement: `notebook_id`, `paragraph_id`, `status`;
- paragraph status: `notebook_id`, `paragraph_id`, `status`;
- output item: `kind`, `text`, where `kind` is exactly `TEXT`, `HTML`, `TABLE`, `IMAGE`, or `UNKNOWN` and text is bounded;
- safe failure detail: `message`, bounded to 4,096 UTF-8 bytes;
- paragraph result: `notebook_id`, `paragraph_id`, `status`, `outputs`, `error`, and `truncated`.

Result fields SHALL reject unknown fields and coercion. A paragraph result SHALL represent only terminal states: `FINISHED` has no error; `ERROR` MAY carry failure outputs (the upstream error text and traceback) and includes safe failure detail; an empty upstream `exception` SHALL NOT produce an empty failure detail. `CANCELLED` has no successful outputs and includes safe failure detail. Output text is individually bounded by the absolute 1 MiB V1 ceiling, while the adapter SHALL enforce the configured total `max_result_bytes`. Public models MUST NOT contain raw upstream state, headers, cookies, credentials, or authorization data.

#### Scenario: Serialize a safe result
- **WHEN** a typed Zeppelin result is serialized for an MCP response
- **THEN** it contains only the fixed public fields and normalized enum values

#### Scenario: Reject an inconsistent paragraph result
- **WHEN** a result combines a non-terminal state, or an error with `FINISHED`
- **THEN** model validation fails before MCP serialization

### Requirement: Normalize Zeppelin paragraph states with a closed mapping
Public paragraph status SHALL be exactly `PENDING`, `RUNNING`, `FINISHED`, `ERROR`, `CANCELLED`, or `UNKNOWN`. Matching SHALL ignore surrounding whitespace and ASCII case. Upstream `READY` and `PENDING` map to `PENDING`; `RUNNING` maps to `RUNNING`; `FINISHED` maps to `FINISHED`; `ERROR` maps to `ERROR`; and `ABORT`, `ABORTED`, `CANCEL`, and `CANCELLED` map to `CANCELLED`. Every other value maps to `UNKNOWN`. Raw upstream state SHALL NOT be returned in a public model; an adapter may log only a separately bounded, control-free state value.

#### Scenario: Normalize a known state
- **WHEN** Zeppelin reports any state in the fixed mapping
- **THEN** the corresponding normalized status is returned

#### Scenario: Normalize an unfamiliar or malformed state
- **WHEN** Zeppelin reports any other string or a non-string state
- **THEN** normalization returns `UNKNOWN` without including the raw value in a result

### Requirement: Expose exactly the Zeppelin notebook lifecycle tools
The Zeppelin plugin SHALL expose exactly `list_notebooks`, `create_notebook`, `add_paragraph`, `run_paragraph`, `get_paragraph_status`, and `get_paragraph_result`.

#### Scenario: List Zeppelin tools
- **WHEN** an MCP client lists tools for a Zeppelin plugin process
- **THEN** the returned tool names are exactly the six approved Zeppelin tool names


### Requirement: List the notebook directory tree
The `list_notebooks` tool SHALL call `GET /api/notebook`, parse the returned `{id, path}` pairs, and return a directory tree where folders are derived from the `/`-separated path segments and leaf nodes carry the opaque notebook ID. The tool SHALL NOT return raw HTTP headers, cookies, or unbounded upstream bodies.

#### Scenario: Return a tree from flat notebook paths
- **WHEN** Zeppelin returns notebooks with paths `/team/note-a` and `/team/note-b`
- **THEN** the tool returns a tree with one `team` folder node containing two leaf notebook nodes, each carrying its opaque `notebook_id`

#### Scenario: Return root-level notebooks
- **WHEN** Zeppelin returns a notebook with path `/Untitled Note`
- **THEN** the tool returns a leaf notebook node at the root of the tree

#### Scenario: Handle an empty notebook list
- **WHEN** Zeppelin returns an empty notebook list
- **THEN** the tool returns an empty tree without making additional requests
### Requirement: Create a notebook
The `create_notebook` tool SHALL create a Zeppelin notebook with the requested validated name and return its opaque notebook ID and name.

#### Scenario: Create a notebook successfully
- **WHEN** Zeppelin accepts a valid notebook name
- **THEN** the tool returns `notebook_id` and `name` without returning raw HTTP headers or cookies

#### Scenario: Reject an invalid notebook name
- **WHEN** the requested name is empty or exceeds the configured length limit
- **THEN** the tool returns `INVALID_INPUT` without calling Zeppelin

### Requirement: Add an allowlisted paragraph
The `add_paragraph` tool SHALL accept an opaque notebook ID, title, and paragraph body. The interpreter SHALL be parsed from the paragraph body's first-line shebang (a line of the form `%<interpreter>`); the tool SHALL NOT inject or modify the shebang. When the body has no leading shebang, the tool SHALL return `INVALID_INPUT` without sending the body to Zeppelin. The parsed interpreter SHALL be matched exactly against the case-sensitive `allowed_interpreters`; a non-allowlisted interpreter SHALL return `INVALID_INPUT` without sending the body to Zeppelin. The body SHALL be sent to Zeppelin verbatim.

#### Scenario: Add an allowed paragraph
- **WHEN** the body begins with a shebang whose interpreter is explicitly allowlisted and Zeppelin accepts the paragraph
- **THEN** the tool returns the notebook ID, paragraph ID, title, and the parsed interpreter, and sends the body verbatim

#### Scenario: Reject a non-allowlisted interpreter
- **WHEN** the body's shebang names an interpreter absent from `allowed_interpreters`
- **THEN** the tool returns `INVALID_INPUT` without sending the paragraph body to Zeppelin

#### Scenario: Reject a body without a shebang
- **WHEN** the paragraph body has no leading shebang line
- **THEN** the tool returns `INVALID_INPUT` without sending the paragraph body to Zeppelin

#### Scenario: Default deny interpreter execution
- **WHEN** `allowed_interpreters` is empty or omitted
- **THEN** every `add_paragraph` request is rejected until an administrator explicitly configures an interpreter


### Requirement: Gate paragraph content with write-operation safety rules
The `add_paragraph` tool SHALL inspect the paragraph body before sending it to Zeppelin and reject content that violates configured write-safety rules. For SQL interpreters (any interpreter whose name contains `sql`), write operations (`INSERT`, `UPDATE`, `DELETE`, `MERGE`, `CREATE`, `ALTER`, `DROP`, `TRUNCATE`, `LOAD`) SHALL only target tables in databases listed in `sql_write_allowed_databases` (default `tmp_dc_ep`). For the `sh` interpreter, only commands whose first token is in `sh_allowed_commands` (default empty) SHALL be allowed. All rejections SHALL return `INVALID_INPUT` without sending the paragraph body to Zeppelin.

#### Scenario: Allow a SQL write to an approved database
- **WHEN** a SQL interpreter paragraph contains `INSERT INTO tmp_dc_ep.my_table` and `sql_write_allowed_databases` includes `tmp_dc_ep`
- **THEN** the paragraph is accepted and sent to Zeppelin

#### Scenario: Reject a SQL write to a non-approved database
- **WHEN** a SQL interpreter paragraph contains `INSERT INTO other_db.my_table` and `sql_write_allowed_databases` is `["tmp_dc_ep"]`
- **THEN** the tool returns `INVALID_INPUT` without sending the paragraph body to Zeppelin

#### Scenario: Allow a SQL read against any database
- **WHEN** a SQL interpreter paragraph contains `SELECT * FROM any_db.my_table`
- **THEN** the paragraph is accepted regardless of `sql_write_allowed_databases`

#### Scenario: Reject a non-allowlisted sh command
- **WHEN** an `sh` interpreter paragraph body starts with `rm` and `sh_allowed_commands` is `["echo", "cat"]`
- **THEN** the tool returns `INVALID_INPUT` without sending the paragraph body to Zeppelin

#### Scenario: Allow an allowlisted sh command
- **WHEN** an `sh` interpreter paragraph body starts with `echo` and `sh_allowed_commands` is `["echo", "cat"]`
- **THEN** the paragraph is accepted and sent to Zeppelin

#### Scenario: Default deny all sh commands
- **WHEN** `sh_allowed_commands` is empty or omitted and an `sh` interpreter paragraph is submitted
- **THEN** the tool returns `INVALID_INPUT` without sending the paragraph body to Zeppelin
### Requirement: Encode opaque Zeppelin identifiers safely
The Zeppelin adapter MUST treat notebook and paragraph IDs as opaque values, validate their size, and encode them as URL path segments rather than concatenating unchecked path text.

#### Scenario: Receive an identifier with path syntax
- **WHEN** a notebook or paragraph ID contains slash, traversal, query, or fragment syntax
- **THEN** the adapter encodes or rejects it so the request cannot target a different REST path

### Requirement: Start paragraph execution without waiting for completion
The `run_paragraph` tool SHALL request execution for an existing paragraph and return the upstream acknowledgement or current normalized state without polling until terminal completion.

#### Scenario: Start a paragraph
- **WHEN** Zeppelin accepts the execution request
- **THEN** the tool returns the notebook ID, paragraph ID, and normalized current status promptly

#### Scenario: Zeppelin rejects execution
- **WHEN** Zeppelin reports that the paragraph cannot be run
- **THEN** the tool returns a safe categorized error without automatically retrying

### Requirement: Inspect normalized paragraph status
The `get_paragraph_status` tool SHALL map Zeppelin paragraph states to `PENDING`, `RUNNING`, `FINISHED`, `ERROR`, `CANCELLED`, or `UNKNOWN`.

#### Scenario: Inspect a running paragraph
- **WHEN** Zeppelin reports a non-terminal running state
- **THEN** the tool returns the notebook ID, paragraph ID, and `RUNNING`

#### Scenario: Receive an unfamiliar state
- **WHEN** Zeppelin returns a state not recognized by the adapter
- **THEN** the tool returns `UNKNOWN` and logs the safe upstream state for diagnosis

#### Scenario: Map Zeppelin 0.10.1 states
- **WHEN** the adapter receives `READY` or `PENDING` it returns `PENDING`; `ABORT` it returns `CANCELLED`; and `RUNNING`, `FINISHED`, `ERROR` map to their identical normalized forms
- **THEN** the closed mapping covers the states verified against Zeppelin 0.10.1

### Requirement: Retrieve bounded paragraph results
The `get_paragraph_result` tool SHALL return normalized paragraph outputs or safe failure details with a configured maximum result size and a `truncated` indicator.

#### Scenario: Retrieve a finished result
- **WHEN** a paragraph is finished and its normalized output is within the configured size limit
- **THEN** the tool returns the IDs, `FINISHED` status, normalized outputs, null error, and `truncated` as false

#### Scenario: Truncate a large result
- **WHEN** normalized output exceeds the configured maximum result size
- **THEN** the tool returns only the permitted prefix and sets `truncated` to true

#### Scenario: Retrieve a failed result
- **WHEN** a paragraph is in an error state
- **THEN** the tool returns `ERROR`, the upstream failure outputs (error text/traceback) bounded by `max_result_bytes`, and safe failure details without credentials, cookies, headers, or an unbounded upstream body

### Requirement: Keep Zeppelin authentication out of tool inputs
The Zeppelin adapter SHALL source configured authentication credentials from environment-backed secrets and SHALL reuse authentication state only inside the selected Zeppelin process.

#### Scenario: Authenticate a Zeppelin request
- **WHEN** a configured Zeppelin operation requires authentication
- **THEN** the adapter supplies credentials or session state internally and no tool argument or result contains them

#### Scenario: Authentication expires
- **WHEN** Zeppelin rejects an expired or invalid session
- **THEN** the current operation returns `AUTHENTICATION_FAILED` without exposing cookies or automatically repeating an execution request

### Requirement: Close the Zeppelin HTTP client
The Zeppelin plugin SHALL use one lazily constructed asynchronous HTTP client per process and close it when the MCP session ends.

#### Scenario: Stop a Zeppelin plugin process
- **WHEN** the MCP session ends after one or more REST calls
- **THEN** the plugin closes its HTTP client and authentication session state
