## MODIFIED Requirements

### Requirement: Expose exactly the Zeppelin notebook lifecycle tools
The Zeppelin plugin SHALL expose exactly `list_notebooks`, `create_notebook`, `add_paragraph`, `run_paragraph`, `get_paragraph_status`, `get_paragraph_result`, and `restart_interpreter`.

#### Scenario: List Zeppelin tools
- **WHEN** an MCP client lists tools for a Zeppelin plugin process
- **THEN** the returned tool names are exactly the seven approved Zeppelin tool names


### Requirement: Validate a fixed Zeppelin V1 configuration
The Zeppelin plugin SHALL accept only these non-sensitive settings: `base_url`, `request_timeout_seconds`, `max_response_bytes`, `max_result_bytes`, `max_notebook_name_chars`, `max_paragraph_title_chars`, `max_paragraph_body_bytes`, `max_opaque_id_chars`, `allowed_interpreters`, `sql_write_allowed_databases`, `sql_forbidden_keywords`, `sh_allowed_commands`, and `restartable_interpreter_settings`. `base_url` MUST be an absolute HTTP or HTTPS URL without user information, query, or fragment; it MAY include a reverse-proxy path and SHALL be normalized without a trailing slash. Numeric settings SHALL use strict numeric types and the following inclusive ranges and defaults: timeout greater than zero and at most 300 seconds (default 30), response bytes 1 through 8 MiB (default 1 MiB), result bytes 1 through 1 MiB (default 65,536), notebook and paragraph-title characters 1 through 1,024 (default 256 each), paragraph-body bytes 1 through 1 MiB (default 65,536), and opaque-ID characters 1 through 4,096 (default 512).

`allowed_interpreters` SHALL default to an immutable empty sequence. Each entry MUST match `[A-Za-z][A-Za-z0-9_.-]{0,63}`. Exact duplicate entries are invalid; matching and uniqueness are case-sensitive. `sql_forbidden_keywords` SHALL default to `("DROP", "TRUNCATE")`. Each entry MUST be an uppercase SQL keyword matching `[A-Z][A-Z_]*`; entries are normalized to uppercase on load, exact duplicates are invalid, and keyword matching at enforcement time is case-insensitive. `restartable_interpreter_settings` SHALL default to an immutable empty sequence. Each entry MUST match `[A-Za-z][A-Za-z0-9_.-]{0,63}`; exact duplicate entries are invalid and matching is case-sensitive. The configuration SHALL reject unknown fields and coercion from strings, booleans, or other incompatible scalar types.

#### Scenario: Load equivalent Zeppelin settings
- **WHEN** equivalent valid Zeppelin settings are supplied in version 1 YAML and JSON files
- **THEN** they produce equivalent validated settings without making a network request

#### Scenario: Default to deny
- **WHEN** `allowed_interpreters` is omitted
- **THEN** the validated value is an empty immutable sequence

#### Scenario: Default forbidden keywords
- **WHEN** `sql_forbidden_keywords` is omitted
- **THEN** the validated value is `("DROP", "TRUNCATE")`

#### Scenario: Override forbidden keywords from the environment
- **WHEN** `ZEPPELIN_SQL_FORBIDDEN_KEYWORDS` supplies a comma-separated list of keywords
- **THEN** the validated value contains exactly those keywords, normalized to uppercase, with precedence over file values

#### Scenario: Default restartable interpreter settings to deny
- **WHEN** `restartable_interpreter_settings` is omitted
- **THEN** the validated value is an empty immutable sequence

#### Scenario: Override restartable interpreter settings from the environment
- **WHEN** `ZEPPELIN_RESTARTABLE_INTERPRETER_SETTINGS` supplies a comma-separated list of setting IDs
- **THEN** the validated value contains exactly those setting IDs, with precedence over file values

#### Scenario: Reject unsafe configuration
- **WHEN** a URL contains credentials, query, fragment, or unsupported scheme, a limit is outside its approved range, an interpreter is malformed or duplicated, a forbidden keyword is malformed or duplicated, a restartable interpreter setting is malformed or duplicated, or an unknown field is present
- **THEN** startup fails with a safe `CONFIG_ERROR` that does not echo the rejected value

## ADDED Requirements

### Requirement: Restart an allowlisted interpreter setting
The `restart_interpreter` tool SHALL accept a `setting_id` (the interpreter group name, e.g. `spark`, `sh`) and reject it with `INVALID_INPUT` before any network call when `setting_id` is not in `restartable_interpreter_settings`. When allowlisted, the tool SHALL call `PUT /api/interpreter/setting/restart/{setting_id}` with the setting ID encoded as a URL path segment. The tool SHALL return a `RestartInterpreterResult` containing `setting_id`, `name`, `group`, and `status` extracted from the upstream response body. The tool SHALL NOT return raw interpreter properties, dependencies, stack traces, option objects, or unbounded upstream bodies. When the upstream returns a non-200 status (including 500 for a nonexistent setting ID), the tool SHALL return an `UPSTREAM_ERROR` with the `setting_id` as a safe identifier. The tool SHALL NOT restart an interpreter setting that is not in the allowlist, regardless of whether it exists upstream.

#### Scenario: Restart an allowlisted interpreter
- **WHEN** `restart_interpreter` is called with `setting_id` `spark` and `restartable_interpreter_settings` includes `spark`
- **THEN** the tool calls `PUT /api/interpreter/setting/restart/spark` and returns a result with `setting_id` `spark` and `status` from the upstream response

#### Scenario: Reject a non-allowlisted interpreter before network
- **WHEN** `restart_interpreter` is called with `setting_id` `spark` and `restartable_interpreter_settings` is empty
- **THEN** the tool returns `INVALID_INPUT` without making a network request

#### Scenario: Reject a malformed setting ID
- **WHEN** `restart_interpreter` is called with `setting_id` containing a space or slash
- **THEN** the tool returns `INVALID_INPUT` without making a network request

#### Scenario: Report upstream failure for nonexistent setting
- **WHEN** `restart_interpreter` is called with an allowlisted `setting_id` that does not exist upstream and Zeppelin returns HTTP 500
- **THEN** the tool returns `UPSTREAM_ERROR` with the `setting_id` as a safe identifier

#### Scenario: Result omits raw properties and dependencies
- **WHEN** `restart_interpreter` succeeds
- **THEN** the returned result contains only `setting_id`, `name`, `group`, and `status` and does not include properties, dependencies, option, or interpreterGroup
