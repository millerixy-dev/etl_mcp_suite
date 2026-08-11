## ADDED Requirements

### Requirement: Validate a fixed DolphinScheduler V1 configuration
The DolphinScheduler plugin SHALL accept only these non-sensitive settings: `base_url`, `status_path`, `request_timeout_seconds`, `max_response_bytes`, and `max_detail_items`. `base_url` MUST be an absolute HTTP or HTTPS URL without user information, query, or fragment and SHALL be normalized without a trailing slash; it MAY include the DolphinScheduler `/dolphinscheduler` context path. `status_path` MUST start with a single `/`, MUST NOT contain a query or fragment, and SHALL default to `/monitor/masters`. Numeric settings SHALL use strict numeric types and the following inclusive ranges and defaults: timeout greater than zero and at most 300 seconds (default 30), response bytes 1 through 8 MiB (default 1 MiB), and detail items 1 through 1,000 (default 100). The configuration SHALL reject unknown fields and coercion from strings, booleans, or other incompatible scalar types.

#### Scenario: Load equivalent DolphinScheduler settings
- **WHEN** equivalent valid settings are supplied in version 1 YAML and JSON files
- **THEN** they produce equivalent validated settings without making a network request

#### Scenario: Default the status path
- **WHEN** `status_path` is omitted
- **THEN** the validated value is `/monitor/masters`

#### Scenario: Reject unsafe configuration
- **WHEN** `base_url` contains credentials, query, or fragment, `status_path` does not start with `/` or contains a query or fragment, a limit is outside its approved range, or an unknown field is present
- **THEN** startup fails with a safe `CONFIG_ERROR` that does not echo any secret value

### Requirement: Source DolphinScheduler authentication from an environment-backed token
The DolphinScheduler V1 secret schema SHALL contain only an optional `token` environment-backed secret reference. When configured, the adapter SHALL send the resolved value as a DolphinScheduler `token` HTTP header on every status request. When `token` is absent, the adapter SHALL send no `token` header and rely on the deployment's authentication behavior. An empty `secrets` object is valid. Token, basic-auth, cookie, and caller-supplied authentication modes are not supported in V1.

#### Scenario: Resolve a configured token
- **WHEN** the `token` secret references an existing environment variable
- **THEN** the resolved value is available only to the adapter and is redacted from representations, validation failures, results, errors, and logs

#### Scenario: Use no authentication
- **WHEN** `secrets` is an empty object
- **THEN** configuration validation succeeds without creating an HTTP client or making a request

### Requirement: Expose only the DolphinScheduler server-status tool
The DolphinScheduler plugin SHALL expose exactly one MCP tool named `get_server_status` and MUST NOT expose project, workflow, task, definition, schedule, or instance operations in V1. The tool SHALL accept no input arguments and SHALL offer no argument that can change the base URL, status path, HTTP method, headers, or request body.

#### Scenario: List DolphinScheduler tools
- **WHEN** an MCP client lists tools for a DolphinScheduler plugin process
- **THEN** the only returned tool name is `get_server_status`

#### Scenario: Prevent arbitrary endpoint access
- **WHEN** an MCP client inspects or invokes `get_server_status`
- **THEN** the client has no argument that can change the base URL, status path, HTTP method, headers, or request body

### Requirement: Query the deployment-configured status endpoint
The `get_server_status` tool SHALL call the configured `status_path` relative to the configured `base_url` using HTTP GET and SHALL interpret the DolphinScheduler 3.1.7 `Result` envelope where `code` equal to `0` means success. The status path MUST NOT be supplied as a tool argument.

#### Scenario: Query a healthy server
- **WHEN** the configured status endpoint returns a `Result` with `code` `0` and a non-empty server list
- **THEN** the tool returns `available` as true, a normalized `HEALTHY` status, the server count, and bounded safe detail fields

#### Scenario: Query a server with no registered nodes
- **WHEN** the configured status endpoint returns a `Result` with `code` `0` and an empty server list
- **THEN** the tool returns `available` as true and a normalized `UNHEALTHY` status

### Requirement: Normalize DolphinScheduler status detail safely
The DolphinScheduler plugin SHALL normalize the `Result.data` server list into a bounded list of safe per-server summaries containing at most `host`, `port`, `res_info`, and `last_heartbeat_time`, SHALL cap the list at `max_detail_items`, and SHALL bound each text field. The plugin MUST NOT return raw HTTP artifacts, response headers, cookies, credentials, the DolphinScheduler `msg` field, or an unbounded upstream body.

#### Scenario: Return bounded server summaries
- **WHEN** the status endpoint returns more servers than `max_detail_items`
- **THEN** the tool returns only the first `max_detail_items` summaries and `server_count` reflects the bounded list

#### Scenario: Drop unknown fields
- **WHEN** a server object contains fields other than the safe summary fields
- **THEN** the tool omits them from the result without failing

### Requirement: Map DolphinScheduler failures to safe error categories
The DolphinScheduler plugin SHALL distinguish connection failure, timeout, authentication failure, permission failure, upstream error, and unexpected response shape, mapping them to `CONNECTION_FAILED`, `TIMEOUT`, `AUTHENTICATION_FAILED`, `PERMISSION_DENIED`, `UPSTREAM_ERROR`, or `UNEXPECTED_RESPONSE` respectively without returning a raw HTTP client exception, response headers, cookies, credentials, or an unbounded body.

#### Scenario: Server is unreachable
- **WHEN** the HTTP client cannot connect to the configured server
- **THEN** the tool returns `CONNECTION_FAILED` without returning a raw HTTP client exception

#### Scenario: Authentication is rejected
- **WHEN** the configured endpoint responds with HTTP 401
- **THEN** the tool returns `AUTHENTICATION_FAILED`

#### Scenario: Permission is denied
- **WHEN** the configured endpoint responds with HTTP 403
- **THEN** the tool returns `PERMISSION_DENIED`

#### Scenario: Upstream reports a business error
- **WHEN** the endpoint returns a `Result` with a non-zero `code` or an HTTP 5xx status
- **THEN** the tool returns `UPSTREAM_ERROR` with a concise safe message

#### Scenario: Server response is unsupported
- **WHEN** the endpoint response cannot be parsed as a DolphinScheduler `Result` envelope or `data` is not a list
- **THEN** the tool returns `UNEXPECTED_RESPONSE` without returning an unbounded raw body

### Requirement: Close the DolphinScheduler HTTP client
The DolphinScheduler plugin SHALL use one lazily constructed asynchronous HTTP client per process and close it when the MCP session ends.

#### Scenario: Stop a DolphinScheduler plugin process
- **WHEN** the MCP session ends after a status request
- **THEN** the plugin closes its HTTP client and owned authentication state
