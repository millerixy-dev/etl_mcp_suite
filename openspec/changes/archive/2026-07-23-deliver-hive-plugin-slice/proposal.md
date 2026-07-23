## Why

The approved product vision is a multi-plugin MCP stdio runner, but shipping all three backends in one change delays the first usable artifact and couples unrelated risk. Teams need a local, secure way to inspect HiveServer2 metadata over MCP today. Delivering the Hive plugin as the first self-contained slice proves the shared runtime, configuration, security, and error boundaries end to end while Zeppelin and DolphinScheduler mature separately.

## What Changes

- Deliver one `mcp-stdio` console command that loads exactly one built-in plugin per child process and serves its tools over stdin/stdout.
- Deliver the shared stdio runtime: versioned YAML/JSON configuration loading, environment-backed secret resolution, non-sensitive environment overrides, secret-safe stderr logging, stable tool-error categories, the explicit built-in plugin registry, and the FastMCP stdio bootstrap lifecycle with lazy resource construction and cleanup.
- Deliver the Hive schema plugin exposing exactly `list_databases`, `list_tables`, and `get_table_schema` over read-only metadata statements (`SHOW DATABASES`, `SHOW TABLES`, `DESCRIBE`, optional `SHOW CREATE TABLE`) with identifier validation, backtick quoting, partition-column separation, DDL parsing, a plugin-local TTL/LRU cache, and PyHive LDAP connectivity.
- Add README installation and usage, redacted Hive configuration examples, MCP host launch guidance, and architecture documents aligned with the Hive slice.
- Defer Zeppelin and DolphinScheduler to separate follow-up changes; they remain out of scope for this slice.
- Supersede the Hive and shared-runtime delivery scope of the umbrella `build-plugin-mcp-stdio` change. That change's remaining Zeppelin and DolphinScheduler scope will be re-scoped as independent follow-up changes.

## Capabilities

### New Capabilities
- `plugin-stdio-runtime`: Local stdio process lifecycle, built-in plugin selection, configuration loading, credential injection, secret-safe logging, stable tool errors, and the shared plugin contract required by the Hive slice.
- `hive-schema-tools`: Read-only HiveServer2 database, table, regular-column, partition-column, and optional DDL metadata inspection.

### Modified Capabilities
None.

## Impact

- Introduces the Python package, `mcp-stdio` console entry point, shared core, explicit registry, and the Hive plugin vertical slice under `src/mcp_stdio`.
- Requires Python 3.10+, uv project management with a committed `uv.lock`, the MCP Python SDK, PyYAML, pydantic, and the pinned `PyHive[hive_pure_sasl]==0.7.0` plus Thrift runtime dependencies.
- Adds unit, contract, MCP protocol-loop, and opt-in HiveServer2 integration tests; integration tests skip without explicit credentials.
- Establishes the security boundaries (no caller-controlled SQL, environment-only credentials, stdout protocol discipline, secret redaction) that all later plugins inherit.
- README, configuration examples, and `docs/architecture/` documents cover the Hive slice only; Zeppelin and DolphinScheduler content is added in follow-up changes.
