## ADDED Requirements

### Requirement: Expose exactly the Zeppelin notebook lifecycle tools
The Zeppelin plugin SHALL expose exactly `create_notebook`, `add_paragraph`, `run_paragraph`, `get_paragraph_status`, and `get_paragraph_result`.

#### Scenario: List Zeppelin tools
- **WHEN** an MCP client lists tools for a Zeppelin plugin process
- **THEN** the returned tool names are exactly the five approved Zeppelin tool names

### Requirement: Create a notebook
The `create_notebook` tool SHALL create a Zeppelin notebook with the requested validated name and return its opaque notebook ID and name.

#### Scenario: Create a notebook successfully
- **WHEN** Zeppelin accepts a valid notebook name
- **THEN** the tool returns `notebook_id` and `name` without returning raw HTTP headers or cookies

#### Scenario: Reject an invalid notebook name
- **WHEN** the requested name is empty or exceeds the configured length limit
- **THEN** the tool returns `INVALID_INPUT` without calling Zeppelin

### Requirement: Add an allowlisted paragraph
The `add_paragraph` tool SHALL accept an opaque notebook ID, title, interpreter name, and paragraph body, and SHALL add the paragraph only when the interpreter is present in the configured allowlist.

#### Scenario: Add an allowed paragraph
- **WHEN** the interpreter is explicitly allowlisted and Zeppelin accepts the paragraph
- **THEN** the tool returns the notebook ID, paragraph ID, title, and interpreter

#### Scenario: Reject a non-allowlisted interpreter
- **WHEN** the requested interpreter is absent from `allowed_interpreters`
- **THEN** the tool returns `INVALID_INPUT` without sending the paragraph body to Zeppelin

#### Scenario: Default deny interpreter execution
- **WHEN** `allowed_interpreters` is empty or omitted
- **THEN** every `add_paragraph` request is rejected until an administrator explicitly configures an interpreter

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
- **THEN** the tool returns `ERROR`, no successful output, and safe failure details without credentials, cookies, headers, or an unbounded upstream body

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
