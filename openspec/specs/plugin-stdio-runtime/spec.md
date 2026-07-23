# plugin-stdio-runtime Specification

## Purpose
TBD - created by archiving change deliver-hive-plugin-slice. Update Purpose after archive.
## Requirements
### Requirement: Reproduce the project with uv on Python 3.10+
The project SHALL declare Python 3.10 or newer, SHALL use uv for project and dependency management, and SHALL commit `uv.lock` so a locked environment can be reproduced without ad hoc pip commands.

#### Scenario: Synchronize the locked environment
- **WHEN** a developer uses the documented uv command on Python 3.10 or newer with an unchanged `pyproject.toml` and `uv.lock`
- **THEN** uv installs the locked dependency set required to run the project and its tests

#### Scenario: Detect dependency drift
- **WHEN** declared dependencies and `uv.lock` are inconsistent during locked synchronization
- **THEN** synchronization fails rather than silently resolving a different environment

### Requirement: Preserve Clean Architecture dependency direction
The project SHALL keep shared core independent of concrete plugins, keep application services independent of MCP and external clients, and prohibit direct imports between plugins.

#### Scenario: Check architecture boundaries
- **WHEN** the architecture contract test scans imports under `src/mcp_stdio`
- **THEN** it finds no core-to-plugin import, application-service import of FastMCP/PyHive/httpx, or plugin-to-plugin import

### Requirement: Run one built-in plugin per stdio process
The system SHALL provide an `mcp-stdio` command that loads exactly one of the built-in `hive`, `zeppelin`, or `dolphinscheduler` plugins and serves only that plugin's MCP tools over stdin/stdout.

#### Scenario: Start a selected plugin
- **WHEN** the runner is started with a supported `--plugin` value and a valid matching configuration
- **THEN** it starts one MCP stdio server containing only the selected plugin's tools

#### Scenario: Reject an unknown plugin
- **WHEN** the runner is started with a plugin name that is not in the explicit built-in registry
- **THEN** startup fails with `CONFIG_ERROR` without importing a module derived from caller input

#### Scenario: Reject a mismatched configuration
- **WHEN** the CLI plugin name differs from the configuration file's `plugin` value
- **THEN** startup fails with `CONFIG_ERROR` before MCP serving begins

### Requirement: Load versioned YAML and JSON configuration
The system SHALL load non-sensitive settings from `.yaml`, `.yml`, or `.json` files with a required configuration version and SHALL reject unknown fields, invalid types, unsupported versions, and unsafe YAML constructs.

#### Scenario: Load equivalent YAML and JSON
- **WHEN** equivalent valid version 1 settings are provided in YAML and JSON files
- **THEN** both files produce equivalent validated plugin configuration

#### Scenario: Reject an unsupported configuration version
- **WHEN** a configuration declares a version other than a supported version
- **THEN** startup fails with `CONFIG_ERROR` identifying the unsupported version

#### Scenario: Reject an unknown field
- **WHEN** a configuration contains a field not defined by the selected plugin schema
- **THEN** startup fails rather than silently ignoring the field

### Requirement: Resolve credentials only from environment variables
The system MUST interpret entries under `secrets` as environment variable names and MUST NOT accept literal credential values from configuration files or MCP tool arguments.

#### Scenario: Resolve configured secret references
- **WHEN** the configuration maps a secret field to an existing environment variable
- **THEN** the plugin receives the environment variable value without exposing it in its MCP schema

#### Scenario: Reject a missing secret
- **WHEN** a required secret references an absent environment variable
- **THEN** startup fails with `CONFIG_ERROR` that may identify the variable name but does not reveal any credential value

#### Scenario: Reject a literal secret object
- **WHEN** a configuration attempts to provide a credential value instead of an environment variable name
- **THEN** startup fails before constructing the plugin runtime

### Requirement: Support non-sensitive environment overrides
The system SHALL allow validated non-sensitive settings to be overridden with `MCP_STDIO__SETTINGS__<FIELD>` environment variables and SHALL apply the same type validation after override resolution.

#### Scenario: Apply a valid override
- **WHEN** a supported non-sensitive override environment variable is present
- **THEN** its parsed value replaces the corresponding file setting

#### Scenario: Reject an invalid override
- **WHEN** an override value cannot be converted to the configured field's type
- **THEN** startup fails with `CONFIG_ERROR`

### Requirement: Preserve stdio protocol integrity
The system MUST write only MCP protocol messages to stdout and MUST write application logs to stderr with credential and authorization data redacted.

#### Scenario: Log during a tool call
- **WHEN** a plugin emits an informational or error log while serving a request
- **THEN** the log appears on stderr and no non-protocol text is written to stdout

#### Scenario: Enable debug logging
- **WHEN** explicit debug logging is enabled
- **THEN** stack traces may be written to stderr but known credential values, authorization headers, tokens, and cookies remain redacted

### Requirement: Avoid network access during startup validation
The system SHALL validate CLI arguments, configuration, secret presence, registry selection, and tool registration without connecting to an upstream service.

#### Scenario: Start with an unreachable backend
- **WHEN** configuration is structurally valid but the configured backend is unreachable
- **THEN** MCP startup succeeds and the connection failure is reported only when a tool invokes that backend

### Requirement: Close selected plugin resources
The system SHALL close the selected plugin's open HTTP clients and other owned resources when stdin closes, the MCP session is cancelled, or startup fails after resource construction.

#### Scenario: MCP host terminates the child process session
- **WHEN** the MCP host closes stdin or cancels the server session
- **THEN** the runner invokes plugin cleanup and exits without leaving owned clients open

### Requirement: Return safe stable tool errors
The system SHALL map plugin failures to `CONFIG_ERROR`, `INVALID_INPUT`, `AUTHENTICATION_FAILED`, `PERMISSION_DENIED`, `NOT_FOUND`, `CONNECTION_FAILED`, `TIMEOUT`, `UPSTREAM_ERROR`, or `UNEXPECTED_RESPONSE` before returning an MCP tool error.

#### Scenario: Return an expected upstream failure
- **WHEN** an upstream service rejects authentication or reports a known error
- **THEN** the tool error contains a stable category, operation, safe identifiers, concise message, and retryability without raw upstream objects or credentials

#### Scenario: Return an unexpected exception
- **WHEN** an uncategorized exception reaches the MCP boundary
- **THEN** the client receives a generic safe error and stderr contains a correlation ID for diagnosis

### Requirement: Isolate plugin processes
The system MUST NOT share memory, credentials, connections, caches, or mutable runtime state between separately launched plugin processes.

#### Scenario: One plugin process fails
- **WHEN** a Hive plugin process exits because of a backend or configuration failure
- **THEN** an independently launched Zeppelin or DolphinScheduler plugin process continues unaffected

