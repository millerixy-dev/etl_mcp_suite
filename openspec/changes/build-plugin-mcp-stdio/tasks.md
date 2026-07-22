## 1. Apply Preflight and Project Foundation

- [x] 1.1 Run the official OpenSpec Apply preflight, read every CLI-returned context file, reconcile this task list with the active specs/design, and initialize durable Superpowers task progress without creating a competing source of truth.
- [x] 1.2 Verify `AGENTS.md` is aligned with the approved multi-plugin architecture, OpenSpec governance, per-plugin security boundaries, and YAML/JSON configuration rules.
- [x] 1.3 Create the Python 3.10+ `pyproject.toml`, `src/mcp_stdio` package skeleton, `mcp-stdio` console entry point, runtime dependency constraints, development dependency group, and committed reproducible `uv.lock` using uv only.
- [x] 1.4 Configure pytest, Ruff with a Python 3.10 target, Pyright, coverage, and the unit/integration test directory layout with integration tests skipped by default.
- [x] 1.5 Add architecture contract tests that enforce core-to-plugin, service-to-infrastructure, and plugin-to-plugin import boundaries.

## 2. Shared stdio Runtime

- [x] 2.1 Add failing tests for versioned YAML/JSON loading, safe YAML behavior, unknown-field rejection, plugin mismatch, non-sensitive environment overrides, environment-backed secret resolution, and secret-safe errors.
- [x] 2.2 Implement core configuration models and loading until the configuration tests pass without performing network calls.
- [x] 2.3 Add failing tests for stable error categories, correlation IDs, stderr logging, stdout protocol discipline, and credential/header/cookie redaction.
- [x] 2.4 Implement the shared error and logging boundary until safe error serialization and redaction tests pass.
- [x] 2.5 Define the minimal plugin lifecycle contract and explicit registry, then test supported selection, unknown-plugin rejection, and the prohibition on dynamic import-by-name.
- [ ] 2.6 Implement bootstrap and FastMCP stdio lifecycle with exactly one selected plugin, lazy resource construction, cleanup on EOF/cancellation/startup failure, and no network side effects during import or startup.
- [ ] 2.7 Add MCP contract and subprocess smoke tests covering startup, exact per-plugin tool registration, protocol-only stdout, stderr logs, and process isolation.

## 3. Hive Schema Plugin

- [ ] 3.1 Add failing tests for Hive configuration, identifier validation/backtick quoting, and rejection before connection creation.
- [x] 3.2 Implement Hive configuration, identifiers, and typed metadata/result models.
- [ ] 3.3 Add failing parser tests for normal columns, partition transitions, repeated headers, blank rows, empty comments, one-based ordinals, and nested complex Hive types.
- [ ] 3.4 Implement `DESCRIBE` and `SHOW CREATE TABLE` response parsing until parser tests pass.
- [ ] 3.5 Add failing cache tests for hit, expiry, TTL-zero disablement, normalized keys, success-only storage, accurate `cached` flags, and the 256-entry LRU bound.
- [ ] 3.6 Implement the plugin-local standard-library TTL/LRU cache until cache tests pass.
- [ ] 3.7 Add failing PyHive adapter tests for the four allowed statement families, LDAP/pure-SASL connection parameters, one connection per uncached invocation, worker-thread execution, and cursor/connection cleanup on every path.
- [ ] 3.8 Implement the Hive gateway and PyHive adapter with safe exception mapping and no caller-controlled SQL.
- [ ] 3.9 Implement and contract-test `list_databases`, `list_tables`, and `get_table_schema`, including exact input/output schemas, optional DDL, cache integration, and the exact three-tool set.
- [ ] 3.10 Add an opt-in HiveServer2 integration test covering LDAP connection, database/table listing, schema parsing, partition detection, optional DDL, and secret-safe failure output.

## 4. Zeppelin Notebook Plugin

- [ ] 4.1 Add failing tests for Zeppelin configuration, default-empty interpreter allowlist, input size limits, opaque ID encoding, authentication secret resolution, result-size limits, and status normalization.
- [ ] 4.2 Implement Zeppelin configuration and typed notebook, paragraph, status, output, and error models.
- [ ] 4.3 Define the Zeppelin gateway and add mock-transport adapter tests for authentication, notebook creation, paragraph creation, execution acknowledgement, status retrieval, result parsing/truncation, HTTP timeouts, and resource cleanup.
- [ ] 4.4 Implement the asynchronous Zeppelin HTTP adapter with encoded path segments, bounded responses, safe error mapping, and one lazy client per process.
- [ ] 4.5 Implement and contract-test `create_notebook`, `add_paragraph`, `run_paragraph`, `get_paragraph_status`, and `get_paragraph_result`, including allowlist rejection before network access and the exact five-tool set.
- [ ] 4.6 Add an opt-in Zeppelin integration test using a dedicated notebook namespace and explicitly allowed test interpreter to cover the complete create/add/run/status/result lifecycle.

## 5. DolphinScheduler Status Plugin

- [ ] 5.1 Add failing tests for DolphinScheduler configuration, environment-backed authentication, configured non-caller-controlled status path, normalized health results, bounded malformed responses, and HTTP resource cleanup.
- [ ] 5.2 Implement the DolphinScheduler gateway and asynchronous HTTP adapter with safe status normalization and error mapping.
- [ ] 5.3 Implement and contract-test the sole `get_server_status` tool and assert that no workflow, task, project, schedule, or instance tools are registered.
- [ ] 5.4 Add an opt-in DolphinScheduler integration test that calls only the configured status endpoint.

## 6. Documentation and Final Verification

- [ ] 6.1 Review `docs/architecture/runtime-flow.md` and `docs/architecture/modules.md` against the implemented lifecycle, module boundaries, imports, and exact plugin tool sets; update both documents for any approved implementation-level detail.
- [ ] 6.2 Add redacted YAML and JSON configuration examples for all three plugins, including environment variable references and Zeppelin interpreter trust warnings.
- [ ] 6.3 Write README installation, `mcp-stdio` usage, MCP host configuration, per-plugin tool contracts, process isolation, security boundaries, and opt-in integration test instructions.
- [ ] 6.4 Run the complete unit and MCP contract suites, Ruff, Pyright, coverage checks, package build, and an installed-console-entry-point smoke test; fix all failures.
- [ ] 6.5 Run each integration suite only where explicit test credentials are available, record skipped suites accurately, and verify that no credential value appears in captured stdout, stderr, reports, examples, or committed files.
- [ ] 6.6 Validate the completed OpenSpec change and reconcile implementation behavior, README, architecture documents, `AGENTS.md`, specs, and tasks before requesting review.
