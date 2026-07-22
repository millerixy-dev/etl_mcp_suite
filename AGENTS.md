# AGENTS.md

## Source of Truth

- OpenSpec SDD governs product changes in this repository.
- The selected active OpenSpec change, its capability specs, `design.md`, and `tasks.md` are the implementation source of truth.
- Do not maintain a competing implementation checklist outside OpenSpec.
- Direct user instructions override project documents. When an approved requirement changes, update the OpenSpec artifacts before continuing implementation.
- `AGENTS.md` defines durable project and development constraints; it must not duplicate every feature requirement from an active change.

## Required Apply Workflow

- Start or resume implementation through `opsx-superpowered-apply`; do not bypass the official OpenSpec Apply protocol.
- Before editing implementation code, run:

  ```bash
  openspec status --change "<change>" --json
  openspec instructions apply --change "<change>" --json
  ```

- Use `changeRoot`, `artifactPaths`, `contextFiles`, progress, and instructions returned by the CLI. Do not assume paths.
- Read every returned context file before coding.
- Work in `tasks.md` order unless dependencies and the Apply instructions explicitly permit another order.
- Mark an OpenSpec task complete only after its implementation, required docs, and task-specific verification have all passed.
- If implementation reveals a missing or ambiguous requirement, stop that task and update the OpenSpec artifacts first.

## Development Discipline

- All behavior, feature, bug-fix, and refactoring work follows strict RED/GREEN/REFACTOR TDD.
- Write the smallest relevant failing test first and run it to confirm the expected failure before writing production code.
- Implement only enough code to make the test pass, then refactor while keeping tests green.
- For unexpected behavior or test failures, use systematic debugging before proposing or implementing a fix.
- Use subagent-driven development only after shared contracts are defined and pending tasks have low coupling and low file overlap.
- A subagent task must include the exact OpenSpec task, relevant artifact paths, mandatory TDD instructions, and the expected verification command.
- Subagents must not independently mark OpenSpec tasks complete. The controlling agent reviews their diff and runs fresh verification first.
- Risky or broad work receives task-scoped review and a final whole-change code review.
- Before any completion claim, run fresh verification and strict OpenSpec validation.

## Project and Dependency Management

- Use uv exclusively for Python project, virtual environment, dependency, lock, and command execution workflows.
- Declare `requires-python = ">=3.10"` and keep production syntax compatible with Python 3.10.
- Commit `uv.lock` and use locked synchronization in verification and CI.
- Do not add pip-, Poetry-, Pipenv-, or Conda-specific project workflows unless an approved OpenSpec change replaces this rule.
- Declare every directly imported third-party package as a direct dependency, even when another package currently installs it transitively.
- Keep runtime dependencies minimal and explain every new dependency in the active design.
- Use `pyproject.toml` for package metadata, console entry points, and tool configuration.

## Architecture

- Organize code as a modular monolith using Clean Architecture dependency direction and vertical plugin slices.
- The shared core owns configuration loading, safe errors, logging, MCP stdio lifecycle, and plugin selection. It contains no backend-specific behavior.
- Each plugin owns its configuration model, domain models, application service, gateway port, external adapter, and MCP tool adapter.
- Application services depend on domain models and gateway interfaces, not FastMCP, PyHive, or HTTP clients.
- External adapters implement plugin gateway interfaces and may depend on PyHive or HTTP libraries.
- MCP tool adapters translate input/output and call application services; they do not contain external integration logic.
- `registry.py` is the only shared module allowed to import concrete plugins.
- Plugins must not import or call one another.
- Add source/architecture tests to enforce these import boundaries.
- Prefer focused files and small, reviewable diffs. Split a module only when its responsibilities or size justify it.

## Runtime Model

- Distribute one Python package and one `mcp-stdio` console command.
- The MCP host launches one independent child process per configured plugin instance.
- Each process loads exactly one built-in plugin and exposes only that plugin's tools.
- Processes share installed code only; they do not share memory, credentials, connections, caches, or mutable state.
- Communicate with the MCP host only through MCP JSON-RPC over stdin/stdout.
- Write only MCP protocol messages to stdout. Send redacted application logs to stderr.
- Do not open an MCP listening port or add HTTP/SSE MCP transport without an approved change.
- Validate local configuration without making a network request. Connect lazily when a tool requires an upstream service.
- Close owned clients, cursors, connections, and sessions on success, failure, cancellation, and process shutdown.

## Plugin Scope

- Version one contains an explicit registry for the built-in `hive`, `zeppelin`, and `dolphinscheduler` plugins.
- Do not add filesystem scanning, import-by-caller-input, Python entry points, hot reload, or third-party plugin loading in version one.
- Hive is metadata-only: no arbitrary SQL, row reads, or DDL execution.
- Zeppelin is execution-capable: interpreters default to deny and require an explicit configuration allowlist.
- DolphinScheduler is observational in version one and exposes server status only.
- Exact tool names, schemas, result shapes, and backend behavior come from the active OpenSpec capability specs.

## Configuration and Secrets

- Load versioned non-sensitive settings from validated YAML or JSON files.
- Use safe YAML loading and reject unknown fields, unsupported versions, plugin mismatches, and invalid types.
- Values under `secrets` are environment variable names, never credential values.
- Credentials, tokens, cookies, and authorization values must not appear in configuration values, MCP tool arguments, tool schemas, tool results, stdout, normal logs, snapshots, or committed fixtures.
- Environment variables may override approved non-sensitive settings and must pass the same validation as file values.
- Do not dump environments, raw connection objects, HTTP headers, cookies, sessions, or unbounded upstream bodies.
- Debug logging remains subject to secret redaction.

## Input and Integration Safety

- Never invent an upstream API, endpoint, configuration key, or response shape. Inspect primary documentation or existing code and capture the decision in OpenSpec.
- Hive database and table identifiers must match `[A-Za-z_][A-Za-z0-9_]*` and be backtick-quoted only after validation.
- Hive may generate only the fixed statement families approved by the active spec.
- Treat Zeppelin notebook and paragraph IDs as opaque bounded values and encode them as URL path segments.
- Validate Zeppelin interpreters against the configured allowlist before sending paragraph content upstream.
- DolphinScheduler status paths come from deployment configuration, never MCP tool input.
- Use read-only or least-privilege service accounts wherever the upstream supports them.
- Do not add analytics, telemetry, retries with side effects, or unrelated network calls.

## Error Handling

- Use stable domain error categories defined by the active design.
- Map backend-specific exceptions at adapter or MCP boundaries; do not expose raw exception representations to MCP clients.
- User-facing errors may contain the operation, safe identifiers, a concise explanation, retryability, and a correlation ID.
- User-facing errors must omit stack traces, credentials, headers, cookies, transport objects, and raw upstream bodies.
- Fail closed on invalid configuration, invalid input, unknown response shapes, or unsupported authentication modes.

## Testing and Verification

- Unit tests use fake gateways, fake PyHive connections/cursors, or mock HTTP transports and require no live backend.
- Test application services independently from MCP and external clients.
- Add MCP contract tests for exact tool sets, input schemas, result shapes, error serialization, stdout discipline, and cleanup.
- Add architecture tests for dependency direction.
- Integration tests are opt-in, use environment-provided credentials, and skip when required settings are absent.
- Never include real credentials in test output, reports, examples, snapshots, or committed files.
- Run the smallest task-specific test first, then the broader affected suite.
- Final verification must include the complete unit/contract suite, lint, type checking, package build, console-entry-point smoke test, and strict OpenSpec validation defined by the active tasks.
- Report exact commands and results. Do not claim an unavailable integration suite passed; report it as skipped.

## Documentation

- Keep README usage, configuration examples, MCP host launch examples, tool contracts, and security warnings aligned with the active specs.
- Keep `docs/architecture/runtime-flow.md` aligned with process startup, request, error, and shutdown behavior.
- Keep `docs/architecture/modules.md` aligned with module ownership, dependency direction, plugin boundaries, and architecture tests.
- Treat architecture documents as explanatory views; when they conflict with an active OpenSpec artifact, update OpenSpec first and then synchronize the documents.
- Use redacted placeholder environment variable names in examples.
- Document the distinction between the local MCP stdio transport and each plugin's upstream HTTP or Thrift connection.
