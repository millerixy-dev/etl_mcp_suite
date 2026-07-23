## MODIFIED Requirements

### Requirement: Load versioned YAML and JSON configuration
The system SHALL load non-sensitive settings from optional `.yaml`, `.yml`, or `.json` files with a required configuration version and SHALL reject unknown fields, invalid types, unsupported versions, and unsafe YAML constructs. The `--config` file argument is optional; when omitted, all settings and secrets SHALL be supplied through plugin-prefix environment variables.

#### Scenario: Load equivalent YAML and JSON
- **WHEN** equivalent valid version 1 settings are provided in YAML and JSON files
- **THEN** both files produce equivalent validated plugin configuration

#### Scenario: Reject an unsupported configuration version
- **WHEN** a configuration declares a version other than a supported version
- **THEN** startup fails with `CONFIG_ERROR` identifying the unsupported version

#### Scenario: Reject an unknown field
- **WHEN** a configuration contains a field not defined by the selected plugin schema
- **THEN** startup fails rather than silently ignoring the field

### Requirement: Support non-sensitive environment overrides
The system SHALL allow validated non-sensitive settings to be overridden with environment variables and SHALL apply the same type validation after override resolution. Plugin-prefix variables (`<PREFIX>_<FIELD>`) take precedence over `MCP_STDIO__SETTINGS__<FIELD>` variables, which take precedence over file values.

#### Scenario: Apply a valid override
- **WHEN** a supported non-sensitive override environment variable is present
- **THEN** its parsed value replaces the corresponding file setting

#### Scenario: Plugin-prefix override wins over file and generic override
- **WHEN** both a `<PREFIX>_<FIELD>` variable and a `MCP_STDIO__SETTINGS__<FIELD>` variable are present alongside a file value
- **THEN** the plugin-prefix value is used after type validation

#### Scenario: Reject an invalid override
- **WHEN** an override value cannot be converted to the configured field's type
- **THEN** startup fails with `CONFIG_ERROR`

## ADDED Requirements

### Requirement: Support environment-variable-only startup
The system SHALL allow a plugin process to start without a `--config` file by reading every settings and secrets field from `<PREFIX>_<FIELD>` environment variables, where `<PREFIX>` is declared by the selected plugin. Required fields whose environment variable is absent SHALL fail with `CONFIG_ERROR` that names the missing variable without revealing any credential value. Optional fields absent from the environment SHALL use the model default.

#### Scenario: Start from environment variables alone
- **WHEN** the runner is started with `--plugin` and no `--config`, and every required `<PREFIX>_<FIELD>` environment variable is set
- **THEN** the plugin runtime is constructed with the environment values and the MCP server starts without reading a file

#### Scenario: Reject a missing required setting variable
- **WHEN** environment-variable-only startup is used and a required settings variable is absent
- **THEN** startup fails with `CONFIG_ERROR` naming the missing environment variable

#### Scenario: Reject a missing required secret variable
- **WHEN** environment-variable-only startup is used and a required secrets variable is absent
- **THEN** startup fails with `CONFIG_ERROR` naming the missing environment variable without revealing any credential value

#### Scenario: Environment variables override file secrets
- **WHEN** a `--config` file is supplied and a `<PREFIX>_<FIELD>` secret variable is also set
- **THEN** the environment value is used instead of the file's secret reference
