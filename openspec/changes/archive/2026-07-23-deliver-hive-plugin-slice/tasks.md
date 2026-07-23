## 1. Project Foundation

- [x] 1.1 Run the OpenSpec Apply preflight, read every CLI-returned context file, and reconcile this task list with the active specs and design.
- [x] 1.2 Verify `AGENTS.md` is aligned with the multi-plugin architecture, OpenSpec governance, per-plugin security boundaries, and YAML/JSON configuration rules.
- [x] 1.3 Create the Python 3.10+ `pyproject.toml`, `src/mcp_stdio` package skeleton, `mcp-stdio` console entry point, runtime dependency constraints, development dependency group, and committed reproducible `uv.lock` using uv only.
- [x] 1.4 Configure pytest, Ruff with a Python 3.10 target, Pyright, coverage, and the unit/integration test directory layout with integration tests skipped by default.
- [x] 1.5 Add architecture contract tests that enforce core-to-plugin, service-to-infrastructure, plugin-to-plugin, and shared-to-plugin import boundaries.

## 2. Shared stdio Runtime

- [x] 2.1 Add failing tests for versioned YAML/JSON loading, safe YAML behavior, unknown-field rejection, plugin mismatch, non-sensitive environment overrides, environment-backed secret resolution, and secret-safe errors.
- [x] 2.2 Implement core configuration models and loading until the configuration tests pass without performing network calls.
- [x] 2.3 Add failing tests for stable error categories, correlation IDs, stderr logging, stdout protocol discipline, and credential/header/cookie redaction.
- [x] 2.4 Implement the shared error and logging boundary until safe error serialization and redaction tests pass.
- [x] 2.5 Define the minimal plugin lifecycle contract and explicit registry, then test supported selection, unknown-plugin rejection, and the prohibition on dynamic import-by-name.
- [x] 2.6 Implement bootstrap and FastMCP stdio lifecycle with exactly one selected plugin, lazy resource construction, cleanup on EOF/cancellation/startup failure, and no network side effects during import or startup.
- [x] 2.7 Add MCP contract and subprocess smoke tests covering startup, exact Hive tool registration, protocol-only stdout, stderr logs, and process isolation.

## 3. Hive Schema Plugin

- [x] 3.1 Add failing tests for Hive configuration, identifier validation/backtick quoting, and rejection before connection creation.
- [x] 3.2 Implement Hive configuration, identifiers, and typed metadata/result models.
- [x] 3.3 Add failing parser tests for normal columns, partition transitions, repeated headers, blank rows, empty comments, one-based ordinals, and nested complex Hive types.
- [x] 3.4 Implement `DESCRIBE` and `SHOW CREATE TABLE` response parsing until parser tests pass.
- [x] 3.5 Add failing cache tests for hit, expiry, TTL-zero disablement, normalized keys, success-only storage, accurate `cached` flags, and the 256-entry LRU bound.
- [x] 3.6 Implement the plugin-local standard-library TTL/LRU cache until cache tests pass.
- [x] 3.7 Add failing PyHive adapter tests for the four application-generated metadata statement families, the pinned driver's validated configured-database `USE` initialization, LDAP/pure-SASL connection parameters, one connection per uncached invocation, worker-thread execution, cancellation waiting, and cursor/connection/transport cleanup on every path.
- [x] 3.8 Implement the Hive gateway and PyHive adapter with safe exception mapping, shielded cancellation cleanup, pinned-driver transport fallback, and no caller-controlled SQL.
- [x] 3.9 Implement and contract-test `list_databases`, `list_tables`, and `get_table_schema`, including exact input/output schemas, optional DDL, cache integration, and the exact three-tool set.
- [x] 3.10 Add an MCP protocol-loop test driving the real FastMCP server through an in-memory client session across `tools/list`, all three `tools/call` success paths, invalid-input rejection, and safe categorized failure, with only the outbound gateway stubbed.
- [x] 3.11 Add an opt-in HiveServer2 integration test covering LDAP connection, database/table listing, schema parsing, partition detection, optional DDL, and secret-safe failure output.

## 4. Hive Slice Documentation

- [x] 4.1 Review `docs/architecture/runtime-flow.md` and `docs/architecture/modules.md` against the implemented lifecycle, module boundaries, imports, and the exact Hive tool set; update both documents for any approved implementation-level detail.
- [x] 4.2 Add redacted YAML and JSON Hive configuration examples, including environment variable references and the metadata-only security warning.
- [x] 4.3 Write README installation, `mcp-stdio` usage, MCP host configuration for the Hive plugin, the three Hive tool contracts, process isolation, security boundaries, and opt-in integration test instructions.

## 5. Final Verification

- [x] 5.1 Run the complete unit, contract, and MCP protocol-loop suites, Ruff, Pyright, coverage checks, package build, and an installed-console-entry-point smoke test; fix all failures.
- [x] 5.2 Run the Hive integration suite only where explicit test credentials are available, record skipped suites accurately, and verify that no credential value appears in captured stdout, stderr, reports, examples, or committed files.
- [x] 5.3 Validate the completed OpenSpec change and reconcile implementation behavior, README, architecture documents, `AGENTS.md`, specs, and tasks before requesting review.
