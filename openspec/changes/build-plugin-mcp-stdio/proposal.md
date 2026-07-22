## Why

Teams often already have REST APIs or database drivers but need a small, local way to expose selected operations as MCP tools without deploying another network service. A shared stdio runtime with isolated, built-in connectors avoids duplicating process, configuration, security, and error-handling code for every backend.

## What Changes

- Add a lightweight Python MCP stdio runner that starts one built-in plugin per child process.
- Add YAML and JSON configuration loading for non-sensitive settings, with credentials supplied through environment variables.
- Add an explicit built-in plugin contract and registry for HiveServer2, Zeppelin, and DolphinScheduler.
- Add a read-only HiveServer2 plugin exposing database, table, and schema metadata tools without arbitrary SQL support.
- Add a Zeppelin plugin covering the minimum notebook execution lifecycle: create a notebook, add a paragraph, execute it, inspect status, and retrieve results or failure details.
- Add a DolphinScheduler plugin exposing only a server-status tool in version one.
- Add consistent secret redaction, safe error mapping, stdio logging discipline, and unit/integration test boundaries across plugins.
- Standardize project management on uv with Python 3.10+, a committed lockfile, and OpenSpec Apply as the implementation task source of truth.

## Capabilities

### New Capabilities

- `plugin-stdio-runtime`: Local stdio process lifecycle, built-in plugin selection, configuration loading, credential injection, logging, and shared plugin contracts.
- `hive-schema-tools`: Read-only HiveServer2 database, table, regular-column, partition-column, and optional DDL metadata inspection.
- `zeppelin-notebook-tools`: Zeppelin notebook and paragraph creation, execution, status inspection, and result retrieval through REST APIs.
- `dolphinscheduler-status-tool`: DolphinScheduler connectivity and server-status inspection without workflow operations.

### Modified Capabilities

None.

## Impact

- Introduces a Python package and one `mcp-stdio` console entry point.
- Requires Python 3.10 or newer and a reproducible uv-managed environment with `uv.lock` committed.
- Adds the MCP Python SDK, YAML parsing, HTTP client, and PyHive pure-SASL dependency chain.
- Adds configuration schemas and MCP host launch examples for each built-in plugin.
- Connects local child processes to Zeppelin REST APIs, HiveServer2 Thrift/LDAP, or DolphinScheduler REST APIs depending on the selected plugin.
- Establishes security boundaries for credentials, caller-controlled input, generated Hive statements, logs, and tool errors.
- Establishes OpenSpec Apply plus Superpowers TDD, task routing, review, and verification as the development discipline.
