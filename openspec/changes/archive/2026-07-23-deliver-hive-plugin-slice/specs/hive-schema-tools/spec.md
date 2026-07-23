## ADDED Requirements

### Requirement: Expose exactly the Hive metadata tools
The Hive plugin SHALL expose exactly `list_databases`, `list_tables`, and `get_table_schema` and MUST NOT expose arbitrary SQL, row reads, or DDL execution.

#### Scenario: List Hive tools
- **WHEN** an MCP client lists tools for a Hive plugin process
- **THEN** the returned tool names are exactly `list_databases`, `list_tables`, and `get_table_schema`

### Requirement: List databases
The `list_databases` tool SHALL execute the fixed `SHOW DATABASES` statement and return database names plus an accurate cache indicator.

#### Scenario: Return databases from HiveServer2
- **WHEN** HiveServer2 returns database rows for `SHOW DATABASES`
- **THEN** the tool returns `databases` as a list of names and `cached` as false for the uncached result

### Requirement: List tables in a validated database
The `list_tables` tool SHALL accept one database identifier, validate it against `[A-Za-z_][A-Za-z0-9_]*`, backtick-quote it, and execute only `SHOW TABLES IN <quoted-database>`.

#### Scenario: List tables successfully
- **WHEN** a valid database name is supplied and HiveServer2 returns table rows
- **THEN** the tool returns the database name, a table-name list, and an accurate cache indicator

#### Scenario: Reject an unsafe database name
- **WHEN** the database argument contains whitespace, punctuation, quoting characters, or SQL fragments
- **THEN** the tool returns `INVALID_INPUT` without opening a Hive connection or executing a statement

### Requirement: Return regular and partition columns
The `get_table_schema` tool SHALL validate and quote database and table identifiers, execute `DESCRIBE`, and return regular columns separately from partition columns.

#### Scenario: Parse a partitioned table
- **WHEN** `DESCRIBE` contains regular columns followed by `# Partition Information`, blank rows, and a repeated `# col_name` header
- **THEN** regular rows appear under `columns`, partition rows appear under `partition_columns`, and marker/header rows are omitted

#### Scenario: Preserve column metadata
- **WHEN** `DESCRIBE` returns complex Hive types and empty or populated comments
- **THEN** the tool preserves complete type strings, converts empty comments to null, and assigns one-based ordinals independently within each column group

#### Scenario: Reject an unsafe table name
- **WHEN** the table argument fails identifier validation
- **THEN** the tool returns `INVALID_INPUT` without opening a Hive connection

### Requirement: Retrieve DDL only when requested
The `get_table_schema` tool SHALL execute `SHOW CREATE TABLE` only when `include_ddl` is true and SHALL otherwise return `ddl` as null.

#### Scenario: Schema without DDL
- **WHEN** `include_ddl` is false or omitted
- **THEN** only `DESCRIBE` is executed and `ddl` is null

#### Scenario: Schema with DDL
- **WHEN** `include_ddl` is true
- **THEN** the tool additionally executes fixed `SHOW CREATE TABLE <quoted-database>.<quoted-table>` and returns the resulting DDL string

### Requirement: Restrict generated Hive statements
The Hive application and adapter code MUST generate only `SHOW DATABASES`, `SHOW TABLES`, `DESCRIBE`, and `SHOW CREATE TABLE` metadata statement families and MUST NOT concatenate unvalidated caller text into a statement. The pinned PyHive 0.7.0 driver SHALL receive the strictly validated configured database and SHALL execute exactly one driver-owned `USE <quoted-configured-database>` statement while constructing each connection; that initialization statement is not tool-generated or caller-controlled, and its internal cursor MUST be closed by the driver.

#### Scenario: Inspect every tool input schema
- **WHEN** an MCP client inspects all Hive tool schemas
- **THEN** no tool accepts SQL text, a WHERE clause, a statement fragment, or a row-query option

#### Scenario: Initialize the configured database through PyHive
- **WHEN** the adapter constructs a PyHive 0.7.0 connection for a validated `settings.database`
- **THEN** the driver executes only `USE <backtick-quoted-configured-database>` before the requested fixed metadata statement and closes the internal initialization cursor

### Requirement: Use isolated lazy Hive connections
Each uncached Hive tool invocation SHALL open one PyHive LDAP connection lazily in a worker thread and SHALL close its cursor and connection on success and failure.

#### Scenario: Successful metadata request
- **WHEN** an uncached metadata operation succeeds
- **THEN** its cursor and connection are closed after rows are collected

#### Scenario: Failed metadata request
- **WHEN** connection, execution, parsing, or response conversion fails
- **THEN** any created cursor and connection are closed and the error is safely categorized

#### Scenario: Cancel an in-flight metadata request
- **WHEN** an MCP request is cancelled after its blocking PyHive worker has started
- **THEN** the adapter waits for the worker to close its cursor and connection before propagating cancellation

#### Scenario: PyHive session close fails
- **WHEN** PyHive 0.7.0 raises while closing the Hive session before closing its owned Thrift transport
- **THEN** the adapter makes a best-effort direct transport close without replacing the operation's primary failure

#### Scenario: Concurrent tool requests
- **WHEN** multiple uncached Hive tools run concurrently
- **THEN** each request uses its own Hive connection and blocking PyHive work does not block MCP protocol processing

### Requirement: Cache successful metadata results only
The Hive plugin SHALL use a plugin-local TTL/LRU cache keyed by tool name and normalized arguments, with a maximum of 256 entries and TTL zero disabling caching.

#### Scenario: Return a cache hit
- **WHEN** an identical successful request is repeated before its positive TTL expires
- **THEN** no new Hive connection is opened and the returned `cached` field is true

#### Scenario: Expire a cache entry
- **WHEN** an entry's TTL has elapsed
- **THEN** the next identical request queries HiveServer2 and returns `cached` as false

#### Scenario: Do not cache an error
- **WHEN** a metadata request fails
- **THEN** no error, credential, cursor, connection, or partial result is stored in the cache

#### Scenario: Enforce the size bound
- **WHEN** a successful insertion would exceed 256 entries
- **THEN** the least recently used entry is evicted

### Requirement: Map Hive failures safely
The Hive plugin SHALL distinguish invalid input, authentication rejection, authorization rejection, not-found objects, transport failures, query failures, and unsupported result shapes without exposing LDAP credentials or raw transport objects.

#### Scenario: LDAP authentication is rejected
- **WHEN** HiveServer2 rejects the configured LDAP credentials
- **THEN** the tool returns `AUTHENTICATION_FAILED` without including the username, password, or raw exception representation

#### Scenario: Ambiguous transport-open failure
- **WHEN** PyHive reports `TTransportException.NOT_OPEN` without a standardized authentication SQL state
- **THEN** the tool conservatively returns `CONNECTION_FAILED` without inspecting or exposing raw exception text
