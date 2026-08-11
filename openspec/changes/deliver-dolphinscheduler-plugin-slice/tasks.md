## 1. Apply Preflight

- [x] 1.1 Run the official OpenSpec Apply preflight (`openspec status` + `instructions apply` + `openspec validate`), read every CLI-returned context file, and reconcile this task list with the DolphinScheduler spec/design. Mark the parent change's tasks 5.1-5.4 as superseded.

## 2. Configuration

- [x] 2.1 Add failing tests for DolphinScheduler configuration: `base_url` validation (scheme, credentials, query, fragment, trailing slash), `status_path` validation and `/monitor/masters` default, numeric ranges and defaults, unknown-field rejection, type-coercion rejection, and an optional environment-backed `token` secret with empty-secrets validity.
- [x] 2.2 Implement `config.py` (`DolphinSchedulerSettings`, `DolphinSchedulerSecrets`) until the configuration tests pass without network access.

## 3. Gateway Port and HTTP Adapter

- [x] 3.1 Add failing mock-transport adapter tests for a healthy `Result` (code 0, non-empty server list), an empty server list, HTTP 401, HTTP 403, HTTP 5xx, non-zero `Result` code, connection failure, timeout, unbounded/malformed response bounding, `token` header application, and HTTP client cleanup.
- [x] 3.2 Define `gateway.py` (`DolphinSchedulerGateway` Protocol, result/error types, `DolphinSchedulerGatewayError`) and implement `http_client.py` (async httpx adapter, one lazy client per process, bounded response read, `token` header, safe error mapping) until the adapter tests pass.

## 4. Application Service and Tool Adapter

- [x] 4.1 Add failing tests for `DolphinSchedulerStatusService` using a fake gateway, covering HEALTHY/UNHEALTHY normalization, detail bounding at `max_detail_items`, unknown-field dropping, and error-category propagation.
- [x] 4.2 Implement `service.py` (application service and immutable `ServerStatusResult` model) until the service tests pass.
- [x] 4.3 Add failing contract tests for the exact single-tool set (`get_server_status`), no input arguments, result shape, stdout protocol discipline, and error serialization.
- [x] 4.4 Implement `tools.py` (`DolphinSchedulerToolAdapter`) and `plugin.py` composition root (load_config -> adapter -> service -> tools -> runtime) until the contract tests pass.

## 5. Integration and Architecture

- [x] 5.1 Add an opt-in DolphinScheduler integration test (skipped without `DOLPHINSCHEDULER_*` env) that calls only the configured status endpoint and asserts secret-safe output.
- [x] 5.2 Confirm architecture boundary tests pass (service independent of httpx/FastMCP, no plugin-to-plugin imports, core independent of plugins) and the exact-tool-set contract test includes only `get_server_status`.

## 6. Verification

- [x] 6.1 Run the full unit/contract suite, Ruff, Pyright, console-entry-point smoke test, and strict OpenSpec validation (`openspec validate --changes` and `openspec validate --specs`); report exact commands and results.
