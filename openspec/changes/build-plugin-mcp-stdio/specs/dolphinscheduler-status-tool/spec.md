## ADDED Requirements

### Requirement: Expose only DolphinScheduler server status
The DolphinScheduler plugin SHALL expose exactly one MCP tool named `get_server_status` and MUST NOT expose project, workflow, task, definition, schedule, or instance operations in v1.

#### Scenario: List DolphinScheduler tools
- **WHEN** an MCP client lists tools for a DolphinScheduler plugin process
- **THEN** the only returned tool name is `get_server_status`

### Requirement: Query the configured status endpoint
The `get_server_status` tool SHALL call the deployment-configured status path relative to the configured DolphinScheduler base URL, and the status path MUST NOT be supplied as a tool argument.

#### Scenario: Query a healthy server
- **WHEN** the configured status endpoint returns a recognized healthy response
- **THEN** the tool returns `available` as true, a normalized status, and safe version or detail fields when present

#### Scenario: Prevent arbitrary endpoint access
- **WHEN** an MCP client inspects or invokes `get_server_status`
- **THEN** the client has no argument that can change the base URL, path, HTTP method, headers, or request body

### Requirement: Normalize unavailable and malformed responses
The DolphinScheduler plugin SHALL distinguish connection failure, timeout, authentication failure, permission failure, unhealthy status, and unexpected response shape.

#### Scenario: Server is unreachable
- **WHEN** the HTTP client cannot connect to the configured server
- **THEN** the tool returns `CONNECTION_FAILED` without returning a raw HTTP client exception

#### Scenario: Server reports unhealthy
- **WHEN** the configured endpoint responds successfully with a recognized unhealthy status
- **THEN** the tool returns `available` as true and the normalized unhealthy status

#### Scenario: Server response is unsupported
- **WHEN** the endpoint response cannot be normalized safely
- **THEN** the tool returns `UNEXPECTED_RESPONSE` without returning an unbounded raw body

### Requirement: Keep DolphinScheduler authentication secret
The DolphinScheduler adapter SHALL source tokens or credentials from environment-backed secrets and MUST NOT include authorization headers, tokens, cookies, or credential values in tool schemas, results, errors, or logs.

#### Scenario: Call an authenticated status endpoint
- **WHEN** the configured endpoint requires authentication
- **THEN** the adapter applies authentication internally and returns only the normalized status result

### Requirement: Close the DolphinScheduler HTTP client
The DolphinScheduler plugin SHALL use one lazily constructed asynchronous HTTP client per process and close it when the MCP session ends.

#### Scenario: Stop a DolphinScheduler plugin process
- **WHEN** the MCP session ends after a status request
- **THEN** the plugin closes its HTTP client and owned authentication state
