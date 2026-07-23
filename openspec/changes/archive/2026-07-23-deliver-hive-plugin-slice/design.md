## Context

The repository already contains approved product guidance for a multi-plugin MCP stdio runner and a working implementation of the shared core plus the Hive plugin, built incrementally. This change formalizes the first deliverable slice: a runnable, documented, and verified Hive metadata MCP server over stdio. It deliberately defers Zeppelin and DolphinScheduler so the shared runtime's configuration, security, error, and lifecycle boundaries are proven by one real backend before more trust-sensitive plugins ship.

The MCP host launches local child processes and communicates over stdin/stdout. Each child process loads exactly one plugin so credentials, connections, caches, and failures are not shared. The package targets Python 3.10+, is managed exclusively with uv, and commits `uv.lock`. OpenSpec change artifacts and the Apply task checklist govern implementation; strict TDD governs execution inside each task.

## Goals / Non-Goals

**Goals:**
- Ship one `mcp-stdio` command that selects and runs the Hive plugin over stdio.
- Deliver the shared runtime the Hive slice depends on: configuration loading, secret resolution, secret-safe logging, stable errors, the explicit registry, and the FastMCP bootstrap lifecycle with cleanup on EOF, cancellation, and startup failure.
- Deliver the Hive plugin's exact three metadata tools with identifier validation, partition separation, optional DDL, TTL/LRU caching, and PyHive LDAP connectivity.
- Prove the slice end to end with an MCP protocol-loop test (in-memory client + real adapter/service/parser/cache, only the outbound gateway stubbed) plus unit, contract, architecture, and an opt-in HiveServer2 integration test.
- Ship README usage, redacted Hive configuration examples, and architecture documents aligned with the Hive slice.

**Non-Goals:**
- Zeppelin or DolphinScheduler plugins, or their configuration, tools, docs, or integration tests.
- HTTP/SSE/Streamable HTTP MCP transports; only stdio is delivered.
- Loading multiple plugins into one process; third-party plugin discovery, entry points, dynamic scanning, or hot reload.
- Arbitrary Hive SQL, row reads, or DDL execution.
- Kerberos, Knox, Hive HTTP transport, or custom Hive TLS behavior.

## Decisions

### 1. One package, one process per selected plugin
The MCP host launches `mcp-stdio --plugin hive --config /path/to/hive.yaml`. Each process creates one MCP server and loads one plugin. Processes share installed code but not memory, credentials, connections, caches, or mutable state. EOF on stdin or cancellation closes the selected runtime. This is preferred over one multi-plugin process for clearer tool namespaces, failure isolation, and credential isolation; separate distributions per plugin were rejected for v1 due to release overhead.

### 2. Modular monolith with vertical plugin slices and Clean Architecture direction
`core` owns configuration, errors, logging, the MCP server adapter, and lifecycle; it contains no backend behavior and imports no plugin. `registry.py` is the only shared module allowed to import concrete plugins. Within the Hive plugin, MCP tool adapters call application services; services depend on domain models and gateway interfaces, never on FastMCP or PyHive; the PyHive adapter implements the gateway interface. Architecture contract tests enforce core-to-plugin, service-to-infrastructure, plugin-to-plugin, and shared-to-plugin boundaries.

### 3. Explicit built-in registry and a small plugin contract
The registry maps the fixed name `hive` (plus placeholders for later plugins) to lazily imported definitions. Selection rejects unknown names with `CONFIG_ERROR` without importing a module derived from caller input, and without network access. The plugin contract exposes `register_tools`, asynchronous idempotent `close`, and `redaction_values` for stderr log redaction.

### 4. Versioned YAML/JSON configuration with environment-only credentials
Non-sensitive settings load from validated `.yaml`/`.yml`/`.json` files with a required version; loading rejects unknown fields, invalid types, unsafe YAML, and plugin mismatches. `secrets` entries are environment variable names, never values. `MCP_STDIO__SETTINGS__<FIELD>` overrides apply to non-sensitive settings with the same validation. Configuration validation performs no network calls. This was chosen over environment-only configuration because Hive has portable non-secret host/port/database settings.

### 5. Deterministic runtime lifecycle and protocol output
Bootstrap parses CLI arguments, loads and validates configuration, resolves secrets, selects the plugin, constructs the runtime without a network request, registers only that plugin's tools, and runs FastMCP on stdio. The server adapter runs the stdio session in a `try/finally` so the runtime is closed on normal exit, exception, or cancellation. Only MCP protocol messages are written to stdout; logging writes redacted text to stderr. Importing a plugin has no network side effects. The Hive plugin opens a new PyHive connection per uncached invocation, closes cursors and connections in `finally` paths, and runs blocking calls with `asyncio.to_thread` wrapped in `asyncio.shield` so cancellation waits for cleanup.

### 6. Hive metadata-only security boundary
Database and table identifiers match `[A-Za-z_][A-Za-z0-9_]*` and are backtick-quoted only after validation. Application and adapter code generate only `SHOW DATABASES`, `SHOW TABLES`, `DESCRIBE`, and optional `SHOW CREATE TABLE`; no tool accepts SQL text. The pinned PyHive constructor also executes one driver-owned `USE` statement from the validated configured database before each metadata operation and closes that cursor; this is not caller-controlled. `DESCRIBE` parsing preserves complex type strings, separates partition columns, uses one-based ordinals, and converts empty comments to null. Successful responses may be cached in a plugin-local TTL/LRU cache (disabled at TTL zero, at most 256 entries, never stores failures or credentials); each response reports whether it came from cache.

### 7. Stable, safe tool errors
Plugin failures map to fixed categories (`CONFIG_ERROR`, `INVALID_INPUT`, `AUTHENTICATION_FAILED`, `PERMISSION_DENIED`, `NOT_FOUND`, `CONNECTION_FAILED`, `TIMEOUT`, `UPSTREAM_ERROR`, `UNEXPECTED_RESPONSE`) at the MCP boundary. User-facing errors contain a stable category, operation, safe identifiers, concise message, retryability, and a correlation ID; they omit stack traces, credentials, headers, cookies, and raw upstream bodies. The inbound adapter serializes errors through FastMCP's `ToolError` so no unexpected exception text reaches the client.

### 8. Slice verification strategy
Beyond unit tests per module and architecture contract tests, the slice includes an MCP protocol-loop test that drives the real FastMCP server through an in-memory client session, exercising `tools/list` and `tools/call` for all three Hive tools across success, invalid-input rejection, and safe categorized failure paths, with only the outbound gateway stubbed. This closes the loop on the vertical slice without a live backend. An opt-in HiveServer2 integration test covers LDAP connection, listing, parsing, partition detection, optional DDL, and secret-safe failure output when explicit credentials are present.

## Risks / Trade-offs

- **[PyHive 0.7.0 is old and has a fragile transitive dependency chain]** -> Use the pure-SASL extra, declare the directly imported Thrift runtime explicitly, lock all versions with uv, spy-test driver initialization and cleanup shapes, and require the Hive integration suite before dependency upgrades.
- **[FastMCP error serialization could expose unexpected exception text]** -> Catch exceptions at the inbound adapter, serialize safe structured errors, and test the real serialization path through the protocol loop.
- **[PyHive 0.7.0 `CloseSession` can leave the transport open]** -> On `connection.close()` failure, best-effort close the owned `_transport`; suppress fallback-close failures so they cannot replace the primary error. Revalidate before upgrading PyHive.
- **[A single distribution installs dependencies unused by the Hive-only process]** -> Accept the small v1 overhead to keep release simple; revisit optional extras only if deployment size becomes material.
- **[Environment overrides can be hard to diagnose]** -> Log which non-secret fields were overridden without logging secret values.
- **[Deferring Zeppelin/DolphinScheduler leaves the registry with placeholder loaders]** -> The registry still lists the three names, but only `hive` has a real runtime; the others raise `NotImplementedError` until their follow-up changes. The Hive slice's contract tests assert the exact Hive tool set only.

## Migration Plan

1. Confirm `AGENTS.md` remains aligned with the multi-plugin architecture, OpenSpec governance, and per-plugin security boundaries.
2. Deliver the shared runtime foundation (configuration, errors, logging, registry, bootstrap, server adapter) with unit and contract tests.
3. Deliver the Hive plugin (configuration, identifiers, models, parser, cache, gateway, PyHive adapter, service, tools) with unit tests.
4. Add the MCP protocol-loop test and architecture contract tests for the Hive slice.
5. Add README installation and usage, redacted Hive configuration examples, MCP host launch guidance, and `docs/architecture/` documents for runtime flow and modules.
6. Run the complete unit, contract, and protocol-loop suites, Ruff, Pyright, coverage, package build, and an installed-console-entry-point smoke test; run the opt-in Hive integration test only where credentials are available.
7. Register the Hive plugin with a local MCP host. Rollback removes the host entry and terminates the process; no persistent platform data is migrated.

## Open Questions

None. Zeppelin and DolphinScheduler behavior is explicitly deferred to separate follow-up changes rather than left unresolved here.
