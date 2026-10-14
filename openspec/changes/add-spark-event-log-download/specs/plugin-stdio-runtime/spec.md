## MODIFIED Requirements

### Requirement: Run one built-in plugin per stdio process
The system SHALL provide an `mcp-stdio` command that loads exactly one of the built-in `hive`, `zeppelin`, `dolphinscheduler`, or `spark` plugins and serves only that plugin's MCP tools over stdin/stdout. The fixed registry MUST NOT use filesystem scanning, third-party entry points or caller-directed imports.

#### Scenario: Start a selected plugin
- **GIVEN** a supported built-in plugin and valid matching configuration
- **WHEN** the runner is started with the corresponding `--plugin` value
- **THEN** it starts one MCP stdio server containing only the selected plugin's tools

#### Scenario: Reject an unknown plugin
- **GIVEN** a plugin name that is not in the explicit built-in registry
- **WHEN** the runner selects that plugin
- **THEN** startup fails with `CONFIG_ERROR` without importing a module derived from caller input

#### Scenario: Reject a mismatched configuration
- **GIVEN** the CLI plugin name differs from the configuration file's `plugin` value
- **WHEN** startup validates configuration
- **THEN** startup fails with `CONFIG_ERROR` before MCP serving begins

#### Scenario: Start only the Spark download surface
- **GIVEN** a structurally valid Spark configuration with an unreachable History Server
- **WHEN** `mcp-stdio --plugin spark` starts
- **THEN** tool registration succeeds locally and includes `fetch_spark_event_log` plus only additional Spark tools specified by their own capabilities, with no Hive, Zeppelin or DolphinScheduler tools and no startup network request

### Requirement: Isolate plugin processes
The system MUST NOT share memory, credentials, connections, live caches or mutable runtime state between separately launched plugin processes. The Spark plugin SHALL allow sequential reuse of evidence in a dedicated configured cache_dir after the previous owner exits, using an exclusive directory lock; concurrent owners MUST NOT share that directory. Evidence lookup MUST match the configured History Server source and exact request selection.

#### Scenario: One plugin process fails
- **GIVEN** independently launched plugin instances
- **WHEN** a Hive plugin process exits because of a backend or configuration failure
- **THEN** independently launched Zeppelin, DolphinScheduler and Spark plugin processes continue unaffected

#### Scenario: Reopen persistent Spark evidence sequentially
- **GIVEN** a Spark process has released its dedicated cache_dir lock on exit
- **WHEN** a later process opens that same cache_dir with the same configured source
- **THEN** it can verify and reuse persisted evidence while constructing new private clients, credentials and in-memory state

#### Scenario: Keep different instances isolated
- **GIVEN** two active Spark instances use different dedicated cache directories
- **WHEN** they download or look up the same application identifier
- **THEN** their evidence and mutable runtime state remain isolated; changing a configured source does not allow reuse of another source's evidence
## ADDED Requirements

### Requirement: Validate raw MCP tool arguments safely
The stdio boundary SHALL validate raw tool argument dictionaries against the registered callable's declared input model before FastMCP preprocessing. Unknown arguments MUST be rejected. Input schemas SHALL forbid additional properties. Explicit strict field annotations, including Spark refresh booleans, MUST be enforced without string coercion. Validation errors SHALL be fixed shared INVALID_INPUT errors and MUST NOT include argument values or raw validation exceptions.

#### Scenario: Reject undeclared credential or path controls
- **GIVEN** a caller supplies a parameter absent from the registered tool schema
- **WHEN** a tool call reaches the stdio boundary
- **THEN** it returns safe INVALID_INPUT without executing the tool or echoing the argument

#### Scenario: Enforce a strict boolean
- **GIVEN** Spark refresh is supplied as string "true"
- **WHEN** raw input validation runs
- **THEN** INVALID_INPUT is returned before SDK conversion or gateway activity
