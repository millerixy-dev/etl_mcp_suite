## Why

The shared stdio runtime, configuration loader, and Hive vertical slice are shipped and archived. The `build-plugin-mcp-stdio` parent change already specifies the Zeppelin plugin's full V1 capability surface (config, auth, input bounds, result models, and the exact five-tool set) and carries RED tests for its config and models. Those tests and spec deltas have no matching implementation, blocking the parent change from closing. Extracting Zeppelin into its own deliverable slice lets it ship independently, exactly as the Hive slice did, without forcing the unrelated DolphinScheduler work into the same delivery.

## What Changes

- Implement the Zeppelin plugin runtime: configuration, typed models, gateway port, asynchronous HTTP adapter, application service, and MCP tool adapter.
- Implement the exact five-tool MCP surface: `create_notebook`, `add_paragraph`, `run_paragraph`, `get_paragraph_status`, `get_paragraph_result`.
- Enforce the default-deny interpreter allowlist, bounded input validation with no normalization, opaque-ID percent-encoding as single path segments, and bounded/truncated result normalization.
- Source credentials from environment-backed secrets only; reuse session state within the single process; close the HTTP client on shutdown.
- Map backend exceptions to safe domain error categories without exposing cookies, headers, or unbounded upstream bodies.
- Add an opt-in integration test for the complete create/add/run/status/result lifecycle.
- Keep the existing Zeppelin config and model RED tests; mark the parent change's Zeppelin tasks as superseded by this slice.

## Capabilities

### New Capabilities

- `zeppelin-notebook-tools`: Zeppelin notebook and paragraph creation, execution, status inspection, and result retrieval through REST APIs, with bounded inputs, default-deny interpreter execution, and safe error mapping.

### Modified Capabilities

- `plugin-stdio-runtime`: the explicit registry and runtime contract already support the built-in `zeppelin` plugin; this slice activates it. No spec-level requirement changes are needed here.

## Impact

- Activates `src/mcp_stdio/plugins/zeppelin/` (currently empty stubs) with a full vertical slice.
- Adds an asynchronous HTTP client dependency (`httpx`) to the Zeppelin adapter only; application services remain SDK-independent.
- Adds the five Zeppelin MCP tools to the exact-tool-set contract test.
- Marks `build-plugin-mcp-stdio` tasks 4.1-4.6 as superseded; the spec deltas move into this slice's `specs/zeppelin-notebook-tools/spec.md`.
- No change to the Hive or DolphinScheduler plugins, the shared core, or the runtime lifecycle.
