## Context

The repository currently contains project guidance for a Hive-only metadata MCP server but no application code. The approved scope now expands the product into a lightweight local MCP stdio runner with three built-in plugins: HiveServer2 schema inspection, a minimal Zeppelin notebook execution lifecycle, and DolphinScheduler server-status inspection.

The MCP host starts local child processes and communicates over stdin/stdout. Each child process must load exactly one plugin so credentials, connections, caches, failures, and dependency state are not shared between backends. The code is distributed as one Python package and uses a Clean Architecture-inspired dependency direction without introducing deep directory hierarchies.

The backends have different trust levels. Hive is metadata-only and must never execute caller-provided SQL. Zeppelin intentionally accepts paragraph content and can execute it, so interpreter selection requires an explicit allowlist. DolphinScheduler v1 is observational and exposes no workflow operations.

The project targets Python 3.10 and newer, is managed exclusively with uv, and commits `uv.lock`. OpenSpec change artifacts and the Apply task checklist govern implementation; Superpowers defines the execution discipline inside each OpenSpec task.

## Goals / Non-Goals

**Goals:**

- Provide one `mcp-stdio` command that selects and runs one built-in plugin over stdio.
- Keep shared runtime concerns independent from backend-specific behavior.
- Make plugin application services testable without MCP, PyHive, or live REST services.
- Load versioned YAML or JSON configuration while sourcing all credential values from environment variables.
- Reserve stdout for MCP protocol traffic and send redacted application logs to stderr.
- Define stable, structured tool responses and safe error categories.
- Provide the agreed Hive, Zeppelin, and DolphinScheduler v1 tool sets.
- Keep installation, startup, and local MCP-host configuration small and predictable.

**Non-Goals:**

- Third-party plugin discovery, Python entry points, dynamic module scanning, or hot reload.
- Loading multiple plugins into one stdio process.
- HTTP, SSE, or Streamable HTTP MCP transports.
- A generic YAML DSL that turns arbitrary REST endpoints or SQL into MCP tools.
- Cross-plugin orchestration or shared sessions.
- Arbitrary SQL, Hive row reads, or Hive DDL execution.
- Zeppelin notebook deletion, notebook import/export, interpreter administration, or automatic long-running polling inside one tool call.
- DolphinScheduler project, workflow, task, or instance operations in v1.
- Kerberos, Knox, Hive HTTP transport, or custom Hive TLS behavior in v1.

## Decisions

### 1. Use one package and one process per selected plugin

The MCP host launches commands such as:

```text
mcp-stdio --plugin hive --config /path/to/hive.yaml
mcp-stdio --plugin zeppelin --config /path/to/zeppelin.yaml
mcp-stdio --plugin dolphinscheduler --config /path/to/dolphinscheduler.json
```

Each process creates one MCP server and loads one plugin. The processes share installed code but do not share memory or runtime resources. The host owns process startup and termination; EOF on stdin or cancellation closes the selected plugin runtime.

This is preferred over one multi-plugin process because it provides clearer tool namespaces, failure isolation, credential isolation, and independent configuration. Separate Python distributions per plugin were rejected for v1 because they add release and compatibility overhead without improving the internal dependency boundaries.

### 2. Use a modular monolith with vertical plugin slices

The package layout is:

```text
src/mcp_stdio/
  __init__.py
  __main__.py
  bootstrap.py
  registry.py
  core/
    config.py
    errors.py
    logging.py
    server.py
  contracts/
    plugin.py
  plugins/
    hive/
      plugin.py
      config.py
      models.py
      service.py
      gateway.py
      pyhive.py
      tools.py
    zeppelin/
      plugin.py
      config.py
      models.py
      service.py
      gateway.py
      http_client.py
      tools.py
    dolphinscheduler/
      plugin.py
      config.py
      service.py
      gateway.py
      http_client.py
      tools.py
```

`core` must not import a plugin. `registry.py` is the only shared module that imports concrete plugins. Within a plugin, MCP tools call application services, application services depend on gateway interfaces and domain models, and external adapters implement the gateway interfaces. Application services must not import the MCP SDK, PyHive, or HTTP clients. Plugins must not import each other.

This “Clean Architecture Lite” layout keeps dependency direction explicit while avoiding a directory per conceptual layer. A plugin may split a file into a subpackage later when size or responsibility warrants it.

### 3. Use an explicit built-in registry and a small plugin contract

The registry maps the fixed names `hive`, `zeppelin`, and `dolphinscheduler` to plugin factories. No filesystem scanning or import-by-user-input is allowed.

The plugin contract covers only the lifecycle required by the runner:

- canonical plugin name;
- plugin-specific configuration validation;
- construction of the application service and external adapter;
- registration of the plugin's MCP tools;
- asynchronous resource cleanup.

The contract does not attempt to model a generic REST endpoint or database query. Backend-specific ports remain inside each plugin.

### 4. Use Python 3.10+, MCP SDK v1, and FastMCP

Version one declares `requires-python = ">=3.10"` and keeps source syntax compatible with Python 3.10. The runtime depends on the stable MCP Python SDK line with an explicit `mcp>=1.27,<2` constraint. FastMCP supplies stdio protocol handling and type-derived tool schemas. Plugin `tools.py` modules are inbound adapters and may depend on FastMCP; application services remain SDK-independent.

MCP SDK v2 is excluded until it has a stable release and a separate compatibility change validates its API and wire behavior. A low-level MCP server was considered but rejected for v1 because the three fixed tool sets do not require custom protocol methods, and FastMCP removes schema and dispatch boilerplate.

### 5. Use versioned YAML/JSON configuration with environment-backed secrets

`--config` is required. Files ending in `.yaml` or `.yml` use safe YAML loading; `.json` uses the standard JSON parser. The root schema contains `version`, `plugin`, `settings`, and `secrets`.

Example:

```yaml
version: 1
plugin: hive
settings:
  host: hive.example.internal
  port: 10000
  database: default
  cache_ttl_seconds: 30
secrets:
  username: HIVE_USERNAME
  password: HIVE_PASSWORD
```

Values under `secrets` are environment variable names, never credential values. Startup resolves the named variables and fails with `CONFIG_ERROR` when a required value is absent. Error messages may name the missing environment variable but must not include its value.

Non-sensitive settings may be overridden with `MCP_STDIO__SETTINGS__<FIELD>`, using uppercase field names. The CLI `--plugin` value and the file's `plugin` value must match. Unknown fields, unsupported config versions, unknown plugins, literal objects under `secrets`, and invalid types fail closed before MCP serving begins. Configuration validation performs no network calls.

This model was selected over environment-only configuration because REST plugins have more non-secret settings and users requested portable YAML/JSON files. Storing credential values in configuration was rejected because local files are commonly committed, copied, or logged accidentally.

### 6. Keep runtime lifecycle and protocol output deterministic

Bootstrap performs these steps:

1. Parse CLI arguments.
2. Load and validate the configuration file.
3. Resolve environment-backed secrets.
4. Select the plugin from the explicit registry.
5. Construct the plugin runtime without making a network request.
6. Register only that plugin's tools.
7. Run FastMCP on stdio.
8. Close plugin resources when the stdio session ends.

Only MCP protocol messages may be written to stdout. Logging is configured once by bootstrap and writes to stderr. Debug mode is explicit and still applies secret redaction. Importing a plugin must have no network side effects.

HTTP plugins use one lazily constructed asynchronous HTTP client per process and close it at shutdown. The Hive plugin opens a new PyHive connection for each uncached tool invocation, closes cursors and connections in `finally` paths, and executes blocking calls with `asyncio.to_thread`.

### 7. Keep tool names local to each isolated plugin process

Because each process exposes one plugin, tool names do not require prefixes.

The Hive process exposes exactly:

- `list_databases`
- `list_tables`
- `get_table_schema`

The Zeppelin process exposes exactly:

- `create_notebook`
- `add_paragraph`
- `run_paragraph`
- `get_paragraph_status`
- `get_paragraph_result`

The DolphinScheduler process exposes exactly:

- `get_server_status`

Adding a tool changes a public MCP contract and requires a spec change. The registry and tool registration tests assert the exact tool set for each plugin.

### 8. Preserve the Hive metadata-only security boundary

Hive uses `PyHive[hive_pure_sasl]==0.7.0` with binary Thrift transport and LDAP authentication. Database and table identifiers must match `[A-Za-z_][A-Za-z0-9_]*` and are backtick-quoted only after validation.

Only four statement families may be generated: `SHOW DATABASES`, `SHOW TABLES`, `DESCRIBE`, and optional `SHOW CREATE TABLE`. No tool accepts SQL text. `DESCRIBE` parsing preserves complex type strings, separates partition columns, uses one-based ordinals, and converts empty comments to null.

Successful Hive metadata responses may be cached in a plugin-local TTL/LRU cache. The cache is disabled at TTL zero, contains at most 256 entries, and never stores failures, credentials, clients, cursors, or connections. Each response reports whether it came from cache.

### 9. Treat Zeppelin as an explicitly execution-capable plugin

The Zeppelin adapter uses REST APIs behind a gateway. `create_notebook` creates and returns an opaque notebook ID. `add_paragraph` accepts a notebook ID, title, interpreter name, and paragraph body, validates the interpreter against `settings.allowed_interpreters`, and returns an opaque paragraph ID. Opaque IDs are encoded as URL path segments and never concatenated without encoding.

`run_paragraph` starts execution and returns the upstream acknowledgement/current state without polling to completion. `get_paragraph_status` returns a normalized state. `get_paragraph_result` returns normalized output only for a completed or failed paragraph and includes safe failure details when available.

Paragraph results are normalized into bounded output items. A configured maximum result size limits the returned UTF-8 payload, and responses indicate when output was truncated.

The default allowed interpreter list is empty, forcing deployment configuration to opt in. Allowing `sh` or another shell-capable interpreter is an explicit high-trust deployment decision. Authentication modes and endpoint differences are handled by the Zeppelin adapter and configuration; credentials are still environment-backed.

Automatic wait-until-complete behavior was rejected because it can consume the MCP host's entire tool timeout. Separate run, status, and result tools let the agent control polling.

### 10. Keep DolphinScheduler v1 observational

The DolphinScheduler adapter exposes a single `get_server_status` tool. It calls the configured status path relative to the configured base URL and returns a normalized result containing availability, reported status, and safe version/details fields when present. It must not return raw headers, tokens, cookies, or unbounded upstream bodies.

The status path is configuration rather than caller input so deployments can accommodate supported DolphinScheduler version differences without creating an arbitrary HTTP tool. Authentication tokens or credentials are environment-backed. No workflow endpoints are implemented or registered.

### 11. Normalize errors at the MCP boundary

Core error categories are:

- `CONFIG_ERROR`
- `INVALID_INPUT`
- `AUTHENTICATION_FAILED`
- `PERMISSION_DENIED`
- `NOT_FOUND`
- `CONNECTION_FAILED`
- `TIMEOUT`
- `UPSTREAM_ERROR`
- `UNEXPECTED_RESPONSE`

Plugins may define internal exceptions but must map them to these categories before they cross the MCP boundary. Tool errors include the category, operation, safe object identifiers, a concise message, and whether retry may succeed. They omit credential values, raw connection objects, cookies, authorization headers, full upstream bodies, and stack traces.

Unexpected exceptions are logged to stderr with a generated correlation ID and returned as a generic `UPSTREAM_ERROR` or `UNEXPECTED_RESPONSE`. Tests exercise the actual FastMCP serialization path to ensure raw exception text is not exposed.

### 12. Manage and lock the full environment with uv

uv is the only project and dependency manager used by development and documented workflows. `pyproject.toml` declares Python 3.10+ and direct dependencies, `uv.lock` is committed, and CI or local verification uses locked synchronization before tests. Direct runtime dependencies are constrained compatible ranges except for the older PyHive release, which is pinned:

- `mcp>=1.27,<2`
- `pydantic>=2.11,<3`
- `PyYAML>=6,<7`
- `httpx>=0.27,<1`
- `PyHive[hive_pure_sasl]==0.7.0`

Development dependencies include pytest, coverage support, Ruff, and Pyright. SQLAlchemy, web frameworks, dotenv loaders, dynamic plugin frameworks, external cache packages, and automatic retry libraries are not needed in v1.

One distribution contains all built-in plugins. The import boundary ensures that starting a REST plugin does not import PyHive or establish Hive state, even though the dependency is installed.

### 13. Test ports, adapters, and stdio behavior at separate levels

Unit tests instantiate application services with fake gateways. Adapter tests use fake PyHive connections/cursors or mock HTTP transports. Configuration tests cover YAML and JSON parity, environment overrides, secret resolution, unknown fields, unsupported versions, and redaction.

MCP contract tests start each plugin through the runner or an in-memory SDK client and assert exact tool names, input schemas, structured result shapes, error serialization, stdout discipline, and cleanup. A subprocess smoke test verifies stdio startup and shutdown.

Integration tests are opt-in and skip unless the relevant environment-backed credentials and base settings are present. Hive integration covers LDAP and metadata parsing. Zeppelin integration uses a dedicated notebook namespace and covers the paragraph lifecycle only for explicitly allowed interpreters. DolphinScheduler integration checks only status. Integration tests must not create workflow definitions or include credentials in reports.

### 14. Make OpenSpec Apply the implementation source of truth

The selected OpenSpec change, its proposal, capability specs, design, and `tasks.md` are the authoritative implementation scope. Implementation starts through the official Apply preflight (`openspec status` followed by `openspec instructions apply`) and uses the paths and context files returned by the CLI. Code changes must not bypass, replace, or maintain a competing task list outside OpenSpec.

Superpowers supplies execution discipline within that protocol:

- behavior and code changes follow strict RED/GREEN/REFACTOR TDD;
- a task checkbox is updated only after task-specific verification passes and no spec/design gap remains;
- unexpected behavior routes through systematic debugging before a fix;
- independent, low-overlap tasks may use subagent-driven development only after shared contracts are defined;
- subagent results require controller review and fresh verification before acceptance;
- risky or broad changes receive task-scoped and final code review;
- completion claims require fresh final verification and strict OpenSpec validation.

If implementation exposes ambiguity or a missing requirement, work stops on that task and updates the OpenSpec artifacts before code proceeds. This preserves OpenSpec as source of truth while applying Superpowers quality gates rather than creating a second planning system.

## Supplemental Architecture Documents

Two permanent explanatory documents expand this design without replacing the OpenSpec source of truth:

- `docs/architecture/runtime-flow.md` describes process startup, common and plugin-specific request flows, error mapping, and shutdown.
- `docs/architecture/modules.md` describes module responsibilities, Clean Architecture dependency direction, plugin boundaries, and architecture verification.

When an approved OpenSpec change modifies runtime or module behavior, update the normative artifacts first and synchronize these documents in the same change.

## Risks / Trade-offs

- **[PyHive 0.7.0 is old and has a fragile transitive dependency chain]** → Use the pure-SASL extra, lock all resolved versions with uv, test the declared Python 3.10+ support matrix, and require the Hive integration suite before dependency upgrades.
- **[FastMCP v1 error serialization could expose unexpected exception text]** → Catch exceptions at the inbound adapter, test the real serialization path, and fall back to the SDK's low-level `CallToolResult` API if safe structured errors cannot be guaranteed.
- **[Zeppelin can execute arbitrary code through allowed interpreters]** → Default to an empty allowlist, require explicit interpreter opt-in, document trust implications, and use a restricted Zeppelin account/interpreter configuration.
- **[A single distribution installs dependencies unused by some processes]** → Accept the small v1 installation overhead to keep release and deployment simple; revisit optional extras only if deployment size becomes material.
- **[Configurable DolphinScheduler status paths vary by deployment]** → Keep the path deployment-controlled rather than caller-controlled, normalize the response, and add adapter fixtures for supported versions.
- **[Environment overrides can be hard to diagnose]** → Log which non-secret fields were overridden without logging values for secret fields.
- **[Separate processes duplicate small amounts of memory]** → Accept the cost in exchange for failure, credential, and connection isolation.

## Migration Plan

1. Verify `AGENTS.md` remains aligned with the approved plugin architecture, OpenSpec governance, and per-plugin security boundaries.
2. Add the Python package, runner, shared core, explicit registry, configuration schemas, and tests without registering external MCP hosts.
3. Add the Hive plugin and validate its unit suite plus opt-in integration test.
4. Add the Zeppelin plugin with a default-empty interpreter allowlist and validate against a dedicated test notebook environment.
5. Add the DolphinScheduler status plugin and validate only its configured status endpoint.
6. Add README installation and one MCP host configuration per plugin.
7. Register plugins with local MCP hosts one at a time. Rollback removes the relevant host entry and terminates that plugin process; no persistent platform data is migrated by the runner.

## Open Questions

None. Backend-specific authentication variants beyond the selected v1 adapters require separate changes rather than unresolved behavior in this design.
