# mcp-stdio

English | [简体中文](README.zh-CN.md)

A lightweight, plugin-based MCP (Model Context Protocol) server that runs over
stdio. Each child process loads exactly one built-in plugin and serves only that
plugin's tools to an MCP host.

The built-in plugins are the **Hive schema plugin** for read-only HiveServer2
metadata inspection (databases, tables, columns, partitions, and optional DDL),
**Zeppelin notebook execution**, and **DolphinScheduler scheduling**.

## Requirements

- Python 3.10 or newer
- [uv](https://docs.astral.sh/uv/) 0.11.28 or newer for project and dependency
  management (0.11.28 is the currently validated version)
- A HiveServer2 endpoint reachable from the process (only when tools are called)

### Install uv on macOS

Install uv with Homebrew:

```bash
brew install uv
```

Or use the [official standalone installer](https://docs.astral.sh/uv/getting-started/installation/):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Open a new terminal if the installer updates your shell configuration, then verify the version:

```bash
uv --version
```

## Installation

> New here? See [`docs/quickstart-macos.md`](docs/quickstart-macos.md) for a
> copy-pasteable end-to-end setup on macOS.

Clone the repository and synchronize the locked environment with uv:

```bash
git clone https://github.com/millerixy-dev/etl_mcp_suite.git
cd etl_mcp_suite
uv sync --frozen
```

This installs the package and its console entry point, `mcp-stdio`, in an
isolated virtual environment using the committed `uv.lock`.

## Agent Skills

The client-neutral Hive, Zeppelin, and natural-language query skills are maintained once at
`skills/hive`, `skills/zeppelin`, and `skills/nl2sql`. Install the same canonical files into the
current project for the MCP client in use:

```bash
./scripts/install-skills-codex.sh
./scripts/install-skills-trae.sh
```

The first command installs into `.codex/skills`; the second installs into `.trae/skills`. To target
another project directory, pass `--project-root /path/to/project`. If any managed skill already
exists, installation stops before copying; review the local customization and pass `--force` only
when it is safe to overwrite the managed skill files. Unrelated skill directories are preserved.

### Install Codex skills together with the local MCP server

For Codex, one command can install the skills, expose the current checkout as an editable uv tool,
and manage the target project's `.codex/config.toml`:

```bash
./scripts/install-skills-codex.sh --project-root /path/to/project --with-mcp
```

This mode runs the equivalent of `uv tool install --editable <this-repository> --reinstall`.
Codex starts the stable `mcp-stdio` command, while each newly started MCP process imports code from
this checkout, so local source edits take effect without rewriting `.codex/config.toml`. The uv tool
executable directory reported by `uv tool dir --bin` must already be on `PATH`.

The installer manages one marked block containing `mcp_servers.hive` and
`mcp_servers.zeppelin`. It uses Codex `env_vars` entries to forward variable names from the
environment that launched Codex; it does not write credential values, Python paths, virtual
environment paths, or `PYTHONPATH` into the TOML file. Export the required values before launching
Codex:

Codex also accepts literal values under `[mcp_servers.<name>.env]`, but those values are stored as
plain text in `.codex/config.toml`. This installer deliberately does not generate that form for
credentials.

```bash
export HIVE_HOST=<hive-host>
export HIVE_USERNAME=<your-ldap-user>
export HIVE_PASSWORD=<your-ldap-password>
export ZEPPELIN_BASE_URL=<zeppelin-base-url>
# Optional Zeppelin login; set both or neither:
export ZEPPELIN_USERNAME=<zeppelin-user>
export ZEPPELIN_PASSWORD=<zeppelin-password>
# JSON array of explicitly allowed interpreters:
export ZEPPELIN_ALLOWED_INTERPRETERS='["spark.sql", "spark.pyspark"]'
```

Missing `HIVE_HOST`, `HIVE_USERNAME`, `HIVE_PASSWORD`, or `ZEPPELIN_BASE_URL` produces a warning
that names only the missing variable; installation still succeeds so the launch environment can be
configured later. Re-running with `--force --with-mcp` refreshes the managed skills and replaces
exactly one managed TOML block while preserving unrelated Codex settings. An existing unmarked Hive
or Zeppelin table is treated as user-owned and is never overwritten. The Trae installer is
currently skill-only and rejects `--with-mcp`.

## Configuration

The Hive plugin can be configured in two ways, used independently or together:

- A versioned YAML or JSON **configuration file** (passed with `--config`), or
- **Environment variables only** (no `--config` needed).

In both cases credentials are supplied **only** through environment variables;
they never appear in configuration values, tool arguments, or logs.

### Configuration file (optional)

See `docs/examples/hive.yaml` and `docs/examples/hive.json` for full examples.
The `--config` argument is optional.

```yaml
version: 1
plugin: hive
settings:
  host: hive.example.internal
  port: 10001
  database: catalog
  cache_ttl_seconds: 60
secrets:
  username: HIVE_USERNAME
  password: HIVE_PASSWORD
```

Export the referenced environment variables before starting the process:

```bash
export HIVE_USERNAME=<your-ldap-user>
export HIVE_PASSWORD=<your-ldap-password>
```

### Environment-variable-only startup

Omit `--config` and supply every field through `<PREFIX>_<FIELD>` environment
variables. For the Hive plugin the prefix is `HIVE`, so each settings and
secrets field maps to one variable:

| Field | Variable | Required |
| --- | --- | --- |
| `settings.host` | `HIVE_HOST` | yes |
| `settings.port` | `HIVE_PORT` | no (default `10000`) |
| `settings.database` | `HIVE_DATABASE` | no (default `default`) |
| `settings.cache_ttl_seconds` | `HIVE_CACHE_TTL_SECONDS` | no (default `30`) |
| `secrets.username` | `HIVE_USERNAME` | yes |
| `secrets.password` | `HIVE_PASSWORD` | yes |

```bash
export HIVE_HOST=<hive-host>
export HIVE_USERNAME=<your-ldap-user>
export HIVE_PASSWORD=<your-ldap-password>
uv run mcp-stdio --plugin hive
```

A missing required variable fails fast with `CONFIG_ERROR` that names the
variable (for example `HIVE_HOST`) without revealing any credential value.

### Precedence

When both a `--config` file and environment variables are present, environment
variables take the highest precedence:

1. `<PREFIX>_<FIELD>` (for example `HIVE_PORT`)
2. `MCP_STDIO__SETTINGS__<FIELD>` (generic override, for example
   `MCP_STDIO__SETTINGS__CACHE_TTL_SECONDS=120`)
3. File value
4. Model default

All override values are validated with the same rules as file values, and the
same precedence applies to secrets: a `<PREFIX>_<FIELD>` value overrides the
file's secret reference.

### Security notes

- Values under `secrets` are environment variable **names**, never credentials.
- The runtime never writes credentials, tokens, or authorization data to
  stdout, MCP results, or logs. Application logs go to stderr with automatic
  secret redaction.
- The Hive plugin is metadata-only: it never accepts or executes caller-provided
  SQL. It generates only `SHOW DATABASES`, `SHOW TABLES`, `DESCRIBE`, and
  optional `SHOW CREATE TABLE` statements against validated identifiers.

## Usage

Run the Hive plugin directly over stdio. With a configuration file:

```bash
uv run mcp-stdio --plugin hive --config docs/examples/hive.yaml
```

Or with environment variables only (no `--config`):

```bash
uv run mcp-stdio --plugin hive
```

> **Note:** in this environment `uv run` may fail with a cache permission
> error. As a fallback, run the venv interpreter directly with
> `PYTHONPATH=src .venv/bin/python -m mcp_stdio --plugin hive`.

### MCP host configuration

Register the Hive plugin with a local MCP host by pointing its command at the
`mcp-stdio` entry point with the `--plugin` flag. The Codex installer above performs this
registration without an absolute checkout path. Each plugin instance runs as
an isolated child process with its own configuration, credentials, connections,
caches, and failure domain. `--config` is optional; an `env`-only configuration
needs no server configuration file at all. Other MCP hosts can use the equivalent
command-name registration and their own environment-variable forwarding feature:

```json
{
  "mcpServers": {
    "hive": {
      "command": "mcp-stdio",
      "args": ["--plugin", "hive"]
    }
  }
}
```

### Debug logging

Pass `--debug` to enable verbose stderr logging. Secrets remain redacted even in
debug mode.

```bash
uv run mcp-stdio --plugin hive --config docs/examples/hive.yaml --debug
```

## Hive tool contracts

The Hive process exposes exactly three read-only tools.

### `list_databases`

Executes the fixed `SHOW DATABASES` statement.

| Field | Type | Description |
| --- | --- | --- |
| `databases` | string[] | Database names |
| `cached` | boolean | Whether the result came from the local cache |

### `list_tables`

Lists tables in one validated database via `SHOW TABLES IN <database>`.

| Argument | Type | Required | Description |
| --- | --- | --- | --- |
| `database` | string | yes | Must match `[A-Za-z_][A-Za-z0-9_]*` |

| Field | Type | Description |
| --- | --- | --- |
| `database` | string | The validated database name |
| `tables` | string[] | Table names |
| `cached` | boolean | Cache indicator |

### `get_table_schema`

Returns regular and partition columns for a table via `DESCRIBE`, plus optional
DDL from `SHOW CREATE TABLE`.

| Argument | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `database` | string | yes | | Must match `[A-Za-z_][A-Za-z0-9_]*` |
| `table` | string | yes | | Must match `[A-Za-z_][A-Za-z0-9_]*` |
| `include_ddl` | boolean | no | `false` | When true, also return `SHOW CREATE TABLE` output |

| Field | Type | Description |
| --- | --- | --- |
| `database` | string | The validated database name |
| `table` | string | The validated table name |
| `columns` | object[] | Regular columns with `name`, `type`, `comment`, `ordinal` |
| `partition_columns` | object[] | Partition columns (same shape) |
| `ddl` | string \| null | DDL text when `include_ddl` is true, otherwise null |
| `cached` | boolean | Cache indicator |

Unsafe identifiers return `INVALID_INPUT` without opening a Hive connection.

## Process isolation

Each `mcp-stdio` process loads exactly one plugin. Processes do not share
memory, credentials, connections, caches, or mutable runtime state. If one
plugin process fails, independently launched plugin processes are unaffected.

## Tool errors

Failures are mapped to stable categories before reaching the MCP client:
`CONFIG_ERROR`, `INVALID_INPUT`, `AUTHENTICATION_FAILED`, `PERMISSION_DENIED`,
`NOT_FOUND`, `CONNECTION_FAILED`, `TIMEOUT`, `UPSTREAM_ERROR`, and
`UNEXPECTED_RESPONSE`. Errors include a category, operation, concise message,
retryability, safe identifiers, and a correlation ID. They never include stack
traces, credentials, headers, cookies, or raw upstream bodies.

## Testing

Run the unit, contract, and MCP protocol-loop suites:

```bash
uv run pytest -m 'not integration'
```

Run lint and type checks:

```bash
uv run ruff check src tests
uv run pyright
```

### Opt-in HiveServer2 integration tests

Integration tests require a live HiveServer2 and are skipped by default. Set the
opt-in variable and provide connection variables to run them:

```bash
MCP_STDIO_HIVE_INTEGRATION=1 \
MCP_STDIO_HIVE_HOST=<host> \
MCP_STDIO_HIVE_PORT=<port> \
MCP_STDIO_HIVE_DATABASE=<database> \
MCP_STDIO_HIVE_TABLE=<table> \
MCP_STDIO_HIVE_USERNAME=<user> \
MCP_STDIO_HIVE_PASSWORD=<password> \
uv run pytest -m integration
```

No credential value appears in captured stdout, stderr, reports, or committed
files.

## Architecture

See `docs/architecture/runtime-flow.md` for process startup, request, error, and
shutdown flows, and `docs/architecture/modules.md` for module ownership,
dependency direction, and plugin boundaries.

The project follows a modular monolith with vertical plugin slices and Clean
Architecture dependency direction: MCP tool adapters call application services;
services depend on domain models and gateway interfaces, never on FastMCP or
PyHive; external adapters implement the gateway interfaces.
