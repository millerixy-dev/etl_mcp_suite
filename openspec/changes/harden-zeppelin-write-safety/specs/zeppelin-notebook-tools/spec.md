## MODIFIED Requirements

### Requirement: Validate a fixed Zeppelin V1 configuration
The Zeppelin plugin SHALL accept only these non-sensitive settings: `base_url`, `request_timeout_seconds`, `max_response_bytes`, `max_result_bytes`, `max_notebook_name_chars`, `max_paragraph_title_chars`, `max_paragraph_body_bytes`, `max_opaque_id_chars`, `allowed_interpreters`, `sql_write_allowed_databases`, `sql_forbidden_keywords`, and `sh_allowed_commands`. `base_url` MUST be an absolute HTTP or HTTPS URL without user information, query, or fragment; it MAY include a reverse-proxy path and SHALL be normalized without a trailing slash. Numeric settings SHALL use strict numeric types and the following inclusive ranges and defaults: timeout greater than zero and at most 300 seconds (default 30), response bytes 1 through 8 MiB (default 1 MiB), result bytes 1 through 1 MiB (default 65,536), notebook and paragraph-title characters 1 through 1,024 (default 256 each), paragraph-body bytes 1 through 1 MiB (default 65,536), and opaque-ID characters 1 through 4,096 (default 512).

`allowed_interpreters` SHALL default to an immutable empty sequence. Each entry MUST match `[A-Za-z][A-Za-z0-9_.-]{0,63}`. Exact duplicate entries are invalid; matching and uniqueness are case-sensitive. `sql_forbidden_keywords` SHALL default to `("DROP", "TRUNCATE")`. Each entry MUST be an uppercase SQL keyword matching `[A-Z][A-Z_]*`; entries are normalized to uppercase on load, exact duplicates are invalid, and keyword matching at enforcement time is case-insensitive. The configuration SHALL reject unknown fields and coercion from strings, booleans, or other incompatible scalar types.

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

#### Scenario: Reject unsafe configuration
- **WHEN** a URL contains credentials, query, fragment, or unsupported scheme, a limit is outside its approved range, an interpreter is malformed or duplicated, a forbidden keyword is malformed or duplicated, or an unknown field is present
- **THEN** startup fails with a safe `CONFIG_ERROR` that does not echo the rejected value

### Requirement: Gate paragraph content with write-operation safety rules
The `add_paragraph` tool SHALL inspect the paragraph body before sending it to Zeppelin through a mandatory, configurable, multi-level safety hook and reject content that violates configured write-safety rules. The safety hook SHALL be the sole path from `add_paragraph` to the gateway and SHALL NOT be bypassable. For SQL interpreters (any interpreter whose name contains `sql`), statements whose leading keyword is in `sql_forbidden_keywords` (default `DROP`, `TRUNCATE`) SHALL be rejected with `INVALID_INPUT` regardless of target database; this forbidden-keyword check SHALL run before the database allowlist. Remaining SQL write operations (`INSERT`, `UPDATE`, `DELETE`, `MERGE`, `CREATE`, `ALTER`, `LOAD`) SHALL only target tables in databases listed in `sql_write_allowed_databases` (default `tmp_dc_ep`). For the `sh` interpreter, only commands whose first token is in `sh_allowed_commands` (default empty) SHALL be allowed. All rejections SHALL return `INVALID_INPUT` without sending the paragraph body to Zeppelin.

#### Scenario: Allow a SQL write to an approved database
- **WHEN** a SQL interpreter paragraph contains `INSERT INTO tmp_dc_ep.my_table` and `sql_write_allowed_databases` includes `tmp_dc_ep`
- **THEN** the paragraph is accepted and sent to Zeppelin

#### Scenario: Reject a SQL write to a non-approved database
- **WHEN** a SQL interpreter paragraph contains `INSERT INTO other_db.my_table` and `sql_write_allowed_databases` is `["tmp_dc_ep"]`
- **THEN** the tool returns `INVALID_INPUT` without sending the paragraph body to Zeppelin

#### Scenario: Reject a forbidden SQL operation on an approved database
- **WHEN** a SQL interpreter paragraph contains `DROP TABLE tmp_dc_ep.my_table` and `sql_forbidden_keywords` includes `DROP` and `sql_write_allowed_databases` includes `tmp_dc_ep`
- **THEN** the tool returns `INVALID_INPUT` without sending the paragraph body to Zeppelin

#### Scenario: Reject TRUNCATE regardless of target database
- **WHEN** a SQL interpreter paragraph contains `TRUNCATE TABLE tmp_dc_ep.my_table` and `sql_forbidden_keywords` includes `TRUNCATE`
- **THEN** the tool returns `INVALID_INPUT` without sending the paragraph body to Zeppelin

#### Scenario: Allow CREATE on an approved database
- **WHEN** a SQL interpreter paragraph contains `CREATE TABLE tmp_dc_ep.my_table (id int)` and `sql_forbidden_keywords` is `["DROP", "TRUNCATE"]` and `sql_write_allowed_databases` includes `tmp_dc_ep`
- **THEN** the paragraph is accepted and sent to Zeppelin

#### Scenario: Allow ALTER on an approved database
- **WHEN** a SQL interpreter paragraph contains `ALTER TABLE tmp_dc_ep.my_table ADD COLUMNS (x int)` and `sql_forbidden_keywords` is `["DROP", "TRUNCATE"]` and `sql_write_allowed_databases` includes `tmp_dc_ep`
- **THEN** the paragraph is accepted and sent to Zeppelin

#### Scenario: Allow a SQL read against any database
- **WHEN** a SQL interpreter paragraph contains `SELECT * FROM any_db.my_table`
- **THEN** the paragraph is accepted regardless of `sql_write_allowed_databases`

#### Scenario: Reject a non-allowlisted sh command
- **WHEN** an `sh` interpreter paragraph body starts with `rm` and `sh_allowed_commands` is `["echo", "cat"]`
- **THEN** the tool returns `INVALID_INPUT` without sending the paragraph body to Zeppelin

#### Scenario: Allow an allowlisted sh command
- **WHEN** an `sh` interpreter paragraph body starts with `echo` and `sh_allowed_commands` is `["echo", "cat"]`
- **THEN** the paragraph is accepted and sent to Zeppelin

#### Scenario: Default deny all sh commands
- **WHEN** `sh_allowed_commands` is empty or omitted and an `sh` interpreter paragraph is submitted
- **THEN** the tool returns `INVALID_INPUT` without sending the paragraph body to Zeppelin
