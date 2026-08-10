## 1. Apply Preflight

- [x] 1.1 Run the official OpenSpec Apply preflight (`openspec status` + `instructions apply` + `openspec validate`), read every CLI-returned context file, and reconcile this task list with the DolphinScheduler status slice and the scheduling spec/design. Confirm `deliver-dolphinscheduler-plugin-slice` scaffolding is the dependency.

## 2. Configuration Expansion

- [x] 2.1 Add failing tests for `default_page_size`, `max_page_size`, and `max_log_bytes` (defaults, ranges, unknown-field rejection, type-coercion rejection) and the expanded allowed-settings closure.
- [x] 2.2 Extend `config.py` (`DolphinSchedulerSettings`) with the three scheduling settings until the configuration tests pass without network access.

## 3. Gateway and HTTP Adapter

- [x] 3.1 Add failing mock-transport adapter tests for the scheduling endpoints: project/workflow/node/process-instance/task-instance list and detail, process-instance task list, task-definition paged list, search variants (including `searchTaskName` for nodes), `start-process-instance` form encoding, log detail pagination, and log download bounding, plus 401/403/5xx/non-zero-code/unexpected-shape mapping.
- [x] 3.2 Extend `gateway.py` (scheduling methods and result/error types) and `http_client.py` (async httpx calls, bounded reads, `token` header, path-segment-safe `projectCode`, safe error mapping) until the adapter tests pass.

## 4. Application Service and Tool Adapter

- [x] 4.1 Add failing tests for the service using a fake gateway, covering `object_type` validation, pagination capping at `max_page_size`, list/detail bounding at `max_detail_items`, related-instance aggregation for `workflow`/`process_instance`/`task_instance`, search parameter mapping, `start_workflow` defaults, log pagination, and link extraction regexes.
- [x] 4.2 Extend `service.py` with the six scheduling operations and result models until the service tests pass.
- [x] 4.3 Add failing contract tests for the exact seven-tool DolphinScheduler set, input schemas, result shapes, stdout protocol discipline, and error serialization.
- [x] 4.4 Extend `tools.py` (`DolphinSchedulerToolAdapter`) to register the six scheduling tools until the contract tests pass.

## 5. Integration and Architecture

- [x] 5.1 Add an opt-in DolphinScheduler integration test (skipped without `DOLPHINSCHEDULER_*` env) covering list/get/search, `start_workflow` with `dry_run`, `get_task_log`, and `extract_log_links` against a real 3.1.7 server, asserting secret-safe output.
- [x] 5.2 Confirm architecture boundary tests pass (service independent of httpx/FastMCP, no plugin-to-plugin imports, core independent of plugins) and the exact-tool-set contract test lists the seven DolphinScheduler tools.

## 6. Documentation and Verification

- [x] 6.1 Reconcile `AGENTS.md`'s DolphinScheduler scope line and the parent change's observational V1 Non-Goal with the execution-capable scheduling surface.
- [x] 6.2 Run the full unit/contract suite, Ruff, Pyright, console-entry-point smoke test, and strict OpenSpec validation (`openspec validate --changes` and `openspec validate --specs`); report exact commands and results.
