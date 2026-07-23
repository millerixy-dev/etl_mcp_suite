## 1. Apply Preflight

- [x] 1.1 Run the official OpenSpec apply preflight (`openspec status` + `instructions apply` + `openspec validate`), read every CLI-returned context file, and reconcile this task list with the Zeppelin spec/design. Mark the parent change's tasks 4.1-4.6 as superseded.

## 2. Configuration and Models (RED tests already exist)

- [x] 2.1 Confirm the existing Zeppelin config and model RED tests fail for the expected reasons, then implement `config.py` (`ZeppelinSettings`, `ZeppelinSecrets`) until the config tests pass.
- [x] 2.2 Implement `models.py` (input validators, status mapping, immutable result models, UTF-8 truncation) until the model tests pass.
- [x] 2.3 Verify config and model tests are green with no network access.

## 3. Gateway Port and HTTP Adapter

- [x] 3.1 Add failing mock-transport adapter tests for notebook creation, paragraph creation, execution acknowledgement, status retrieval, result parsing/truncation, opaque-ID path encoding, HTTP timeouts, auth failure mapping, and resource cleanup.
- [x] 3.2 Define `gateway.py` (ZeppelinGateway Protocol, result/error types, ZeppelinGatewayError) and implement `http_client.py` (async httpx adapter, one lazy client per process, encoded path segments, bounded responses, safe error mapping) until the adapter tests pass.

## 4. Application Service and Tool Adapter

- [x] 4.1 Add failing tests for `ZeppelinNotebookService` using a fake gateway, covering allowlist rejection before gateway calls, result truncation, and status normalization.
- [x] 4.2 Implement `service.py` until the service tests pass.
- [x] 4.3 Add failing contract tests for the exact five-tool set (`create_notebook`, `add_paragraph`, `run_paragraph`, `get_paragraph_status`, `get_paragraph_result`), input schemas, result shapes, and allowlist-before-network rejection.
- [x] 4.4 Implement `tools.py` (ZeppelinToolAdapter) and `plugin.py` composition root until the contract tests pass.

## 5. Integration and Architecture

- [x] 5.1 Add an opt-in Zeppelin integration test (skipped without `MCP_STDIO_ZEPPELIN_*` env) covering the complete create/add/run/status/result lifecycle with a dedicated notebook namespace and explicitly allowed test interpreter.
- [x] 5.2 Confirm architecture boundary tests pass (service independent of httpx/FastMCP, no plugin-to-plugin imports, core independent of plugins).

## 6. List Notebooks Tool

- [x] 6.1 Add failing tests for `list_notebooks`: mock-transport adapter test returning a directory tree from flat `{id, path}` pairs, service test, and contract test asserting the exact six-tool set.
- [x] 6.2 Implement `list_notebooks` in the gateway, HTTP adapter, service, models, and tool adapter until all tests pass.

## 7. Paragraph Write-Safety Gate

- [x] 7.1 Add failing tests for SQL write-target validation (allow writes to `tmp_dc_ep`, reject writes to other databases, allow reads anywhere) and sh command allowlist (reject non-allowlisted, allow allowlisted, default deny).
- [x] 7.2 Add `sql_write_allowed_databases` and `sh_allowed_commands` to ZeppelinSettings, implement content-safety validators in models.py, and wire them into the service `add_paragraph` gate before network access.

## 8. Verification

- [x] 8.1 Run the full unit/contract suite, Ruff, Pyright, console-entry-point smoke test, and strict OpenSpec validation; report exact commands and results.
