## Why

The shared stdio runtime, configuration loader, error and logging boundary, explicit registry, Hive vertical slice, and Zeppelin vertical slice are implemented and archived or complete. The `build-plugin-mcp-stdio` parent change already specifies the DolphinScheduler V1 capability surface (one status tool, a deployment-configured status path, environment-backed authentication, response normalization, and HTTP client cleanup) and carries empty stubs plus a `NotImplementedError` runtime builder in `src/mcp_stdio/plugins/dolphinscheduler/`. The registry already imports the `dolphinscheduler` definition. Those stubs have no implementation and no tests, blocking the parent change's section 5 from closing. The parent design intentionally deferred the exact DolphinScheduler REST API facts; extracting DolphinScheduler into its own deliverable slice lets it ship independently, exactly as the Hive and Zeppelin slices did, while capturing the DolphinScheduler 3.1.7 monitor API facts that the parent design left open.

## What Changes

- Implement the DolphinScheduler plugin runtime: configuration, gateway port, asynchronous HTTP adapter, application service, and MCP tool adapter, behind the shared core's configuration loading and stdio lifecycle.
- Implement the sole `get_server_status` MCP tool with no input arguments and assert that no workflow, task, project, definition, schedule, or instance tools are registered.
- Query the deployment-configured status path (default `/monitor/masters` relative to the configured `base_url`, which includes the DolphinScheduler `/dolphinscheduler` context path) and normalize the DolphinScheduler 3.1.7 `Result` envelope (`{code, msg, data}`, `code` `0` equals success).
- Authenticate each request with a `token` HTTP header sourced from an environment-backed secret; map HTTP 401 to `AUTHENTICATION_FAILED`, 403 to `PERMISSION_DENIED`, connection failure to `CONNECTION_FAILED`, timeout to `TIMEOUT`, non-zero `Result` codes and 5xx to `UPSTREAM_ERROR`, and unrecognized response shapes to `UNEXPECTED_RESPONSE`.
- Normalize the server list into safe, bounded detail fields (count plus per-server host, port, resource info, and last heartbeat time) without returning raw HTTP artifacts, headers, cookies, credentials, the DolphinScheduler `msg` field, or unbounded upstream bodies.
- Use one lazily constructed asynchronous httpx client per process and close it when the MCP session ends.
- Add an opt-in integration test that calls only the configured status endpoint.
- Mark the parent change's tasks 5.1-5.4 as superseded by this slice.

## Capabilities

### New Capabilities

- `dolphinscheduler-status-tool`: DolphinScheduler 3.1.7 connectivity and server-status inspection through the monitor REST API, with a deployment-configured status path, environment-backed token authentication, bounded response normalization, safe error mapping, and no workflow operations.

### Modified Capabilities

- `plugin-stdio-runtime`: the explicit registry and runtime contract already support the built-in `dolphinscheduler` plugin; this slice activates it. No spec-level requirement changes are needed here.

## Impact

- Activates `src/mcp_stdio/plugins/dolphinscheduler/` (currently empty stubs with a `NotImplementedError` runtime builder) with a full vertical slice.
- Reuses the existing `httpx` dependency already added by the Zeppelin adapter; no new third-party dependency is introduced.
- Adds the single `get_server_status` tool to the exact-tool-set contract test.
- Marks `build-plugin-mcp-stdio` tasks 5.1-5.4 as superseded; the concrete spec deltas move into this slice's `specs/dolphinscheduler-status-tool/spec.md`.
- No change to the Hive or Zeppelin plugins, the shared core, or the runtime lifecycle.
