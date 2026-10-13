# mcp-stdio

English | [简体中文](README.zh-CN.md)

A lightweight, plugin-based MCP (Model Context Protocol) server that runs over
stdio. Each child process loads exactly one built-in plugin and serves only that
plugin's tools to an MCP host.

The built-in plugins are the **Hive schema plugin** for read-only HiveServer2
metadata inspection (databases, tables, columns, partitions, and optional DDL),
**Zeppelin notebook execution**, **DolphinScheduler scheduling**, and **Spark event-log download**.

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

## Local development and production isolation

The following is a deployment guide. Existing MCP registrations are not migrated
until the release is installed and their entry points are switched explicitly.

Keep the source checkout and the Codex MCP runtime in separate directories:

```text
Development checkout: /absolute/path/to/hive_cli_mcp_stdio
Production root:      /absolute/path/to/hive-cli-mcp-stdio-prod
```

The development checkout owns source files, worktrees, `.venv`, tests, and editable installs.
Codex production registrations must point only to an immutable wheel release under the production
root. They must not point to the checkout, its `.venv`, an editable uv tool, or a `PYTHONPATH`
containing the checkout. `./scripts/install-skills-codex.sh --with-mcp` is therefore a development
workflow; do not use its editable MCP registration as the local production runtime.

Create a release from a tracked, clean commit with locked runtime dependencies:

```bash
set -e
PROJECT_DIR=/absolute/path/to/hive_cli_mcp_stdio
PROD_ROOT=/absolute/path/to/hive-cli-mcp-stdio-prod
RELEASE_ID="$(date +%Y%m%d%H%M%S)-$(git -C "$PROJECT_DIR" rev-parse --short=12 HEAD)"
RELEASE_DIR="$PROD_ROOT/releases/$RELEASE_ID"

test -z "$(git -C "$PROJECT_DIR" status --porcelain --untracked-files=no)"
mkdir -p "$RELEASE_DIR/dist"

uv build --project "$PROJECT_DIR" --wheel --out-dir "$RELEASE_DIR/dist"
uv export \
  --project "$PROJECT_DIR" \
  --locked \
  --no-dev \
  --no-emit-project \
  --format requirements.txt \
  --output-file "$RELEASE_DIR/runtime-requirements.txt"

uv venv --python 3.12 "$RELEASE_DIR/venv"
uv pip install \
  --python "$RELEASE_DIR/venv/bin/python" \
  --requirement "$RELEASE_DIR/runtime-requirements.txt"

WHEEL_PATH="$(find "$RELEASE_DIR/dist" -maxdepth 1 -name '*.whl' -print -quit)"
uv pip install \
  --python "$RELEASE_DIR/venv/bin/python" \
  --no-deps \
  "$WHEEL_PATH"

"$RELEASE_DIR/venv/bin/mcp-stdio" --help
ln -sfn "$RELEASE_DIR" "$PROD_ROOT/current"
```

The commands package the source and install it with locked dependencies in an independent
production environment:

| Command | Purpose and key options |
| --- | --- |
| `uv build --project ... --wheel --out-dir ...` | Build the project in `--project` into a `.whl` file under `--out-dir`. The wheel contains the project's code; third-party dependencies are installed separately. |
| `uv export --project ... --locked --no-dev --no-emit-project --format requirements.txt --output-file ...` | Export dependencies from `uv.lock`. `--locked` rejects changes that would require updating the lockfile; `--no-dev` excludes the development dependency group; `--no-emit-project` leaves out the project itself. `--format` selects the requirements format and `--output-file` sets its destination. |
| `uv venv --python 3.12 ...` | Create an isolated virtual environment using Python 3.12 at the specified path. Each release has its own environment. |
| `uv pip install --python ... --requirement ...` | Install the exported dependencies. `--python` selects the target environment's interpreter; `--requirement` selects the dependency file. |
| `uv pip install --python ... --no-deps "$WHEEL_PATH"` | Install the project wheel into the same environment. `--no-deps` skips dependency resolution and installation because the preceding step already installed the locked dependencies. |

`uv pip` is uv's package installation interface; it does not invoke the system `pip`.
Installing a wheel copies the packaged code into the release environment rather than linking
to the development source as an editable install would. Later source edits therefore do not
change that installed release.

The final two commands are not uv commands. `mcp-stdio --help` checks that the console entry
point starts, but does not test a Zeppelin connection. `ln -sfn` updates the `current` symlink
to select the new release; already-running MCP processes must still be restarted to load it.

The following example keeps plugin settings and credentials as explicit Codex
environment entries and omits `--config`. The project-local `.codex/config.toml` is ignored by Git
because it contains plain-text credentials; restrict it to the current user with `chmod 600`.
All three project registrations should use the same production entry point:

```toml
[mcp_servers.hive]
command = "/absolute/path/to/hive-cli-mcp-stdio-prod/current/venv/bin/mcp-stdio"
args = ["--plugin", "hive"]

[mcp_servers.hive.env]
HIVE_HOST = "<hive-host>"
HIVE_USERNAME = "<hive-user>"
HIVE_PASSWORD = "<hive-password>"

[mcp_servers.zeppelin]
command = "/absolute/path/to/hive-cli-mcp-stdio-prod/current/venv/bin/mcp-stdio"
args = ["--plugin", "zeppelin"]

[mcp_servers.zeppelin.env]
ZEPPELIN_BASE_URL = "<zeppelin-base-url>"
ZEPPELIN_USERNAME = "<zeppelin-user>"
ZEPPELIN_PASSWORD = "<zeppelin-password>"
ZEPPELIN_ALLOWED_INTERPRETERS = "[\"spark.sql\", \"spark.pyspark\"]"
ZEPPELIN_RESTARTABLE_INTERPRETER_SETTINGS = "[\"<actual-setting-id>\"]"

[mcp_servers.dolphinscheduler]
command = "/absolute/path/to/hive-cli-mcp-stdio-prod/current/venv/bin/mcp-stdio"
args = ["--plugin", "dolphinscheduler"]

[mcp_servers.dolphinscheduler.env]
DOLPHINSCHEDULER_BASE_URL = "<dolphinscheduler-base-url>"
DOLPHINSCHEDULER_TOKEN = "<dolphinscheduler-token>"
```

```bash
chmod 600 "$PROJECT_DIR/.codex/config.toml"
```

Confirm that the installed module resolves inside the production release, then restart the MCP
children so Codex reads the new `current` target:

```bash
"$PROD_ROOT/current/venv/bin/python" -c \
  'import pathlib, mcp_stdio; print(pathlib.Path(mcp_stdio.__file__).resolve())'
codex mcp list --json
```

Keep previous release directories for rollback. Point `current` at the previous release and restart
the MCP children; no source checkout or dependency reinstall is needed:

```bash
ln -sfn "$PROD_ROOT/releases/<previous-release>" "$PROD_ROOT/current"
```

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

The installer manages one marked block containing `mcp_servers.hive`,
`mcp_servers.zeppelin`, and `mcp_servers.dolphinscheduler`. It uses Codex `env_vars` entries to forward variable names from the
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
export DOLPHINSCHEDULER_BASE_URL=http://<ds-host>:12345/dolphinscheduler
# Optional DolphinScheduler API token:
export DOLPHINSCHEDULER_TOKEN=<dolphinscheduler-api-token>
```

Missing `HIVE_HOST`, `HIVE_USERNAME`, `HIVE_PASSWORD`, or `ZEPPELIN_BASE_URL` produces a warning
that names only the missing variable; installation still succeeds so the launch environment can be
configured later. Re-running with `--force --with-mcp` refreshes the managed skills and replaces
exactly one managed TOML block while preserving unrelated Codex settings. An existing unmarked Hive,
Zeppelin, or DolphinScheduler table is treated as user-owned and is never overwritten.

### Add the DolphinScheduler MCP server to Codex

The Codex installer creates this entry automatically with `--with-mcp`:

```toml
[mcp_servers.dolphinscheduler]
command = "mcp-stdio"
args = ["--plugin", "dolphinscheduler"]
env_vars = [
  "DOLPHINSCHEDULER_BASE_URL",
  "DOLPHINSCHEDULER_TOKEN",
]
```

`DOLPHINSCHEDULER_BASE_URL` is required and must be an absolute `http` or
`https` URL without credentials, including the deployment context path when it
uses one (for example, `http://ds-host:12345/dolphinscheduler`).
`DOLPHINSCHEDULER_TOKEN` is optional. It is forwarded by name; never put its
value in the TOML file.

### Add all three MCP servers to Trae

The Trae installer also accepts `--with-mcp`. It installs the editable tool and creates `<project>/.trae/mcp.json` with the **Hive, Zeppelin, and DolphinScheduler** server entries:

```bash
./scripts/install-skills-trae.sh --project-root /path/to/project --with-mcp
```

The JSON config contains only `mcp-stdio` commands and plugin arguments, not
environment values. Start Trae with the required `HIVE_*`, `ZEPPELIN_*`, and
`DOLPHINSCHEDULER_*` variables already exported. To prevent loss of user
configuration, the installer refuses to replace an existing `.trae/mcp.json`.

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

## Zeppelin tool contracts

The Zeppelin process exposes exactly nine tools. IDs are opaque, case-sensitive strings; callers
must preserve them exactly and must not infer a setting ID from an interpreter name, setting name,
or paragraph body.

| Tool | Arguments | Exact result fields |
| --- | --- | --- |
| `list_notebooks` | none | `nodes: NotebookTreeNode[]` |
| `create_notebook` | `name: string` | `notebook_id`, `name` |
| `add_paragraph` | `notebook_id: string`, `title: string`, `body: string` | `notebook_id`, `paragraph_id`, `title`, `interpreter` |
| `run_paragraph` | `notebook_id: string`, `paragraph_id: string` | `notebook_id`, `paragraph_id`, `status` |
| `get_paragraph_status` | `notebook_id: string`, `paragraph_id: string` | `notebook_id`, `paragraph_id`, `status` |
| `get_paragraph_result` | `notebook_id: string`, `paragraph_id: string` | `notebook_id`, `paragraph_id`, `status`, `outputs`, `truncated`, `error` |
| `get_interpreter_bindings` | `notebook_id: string` | `notebook_id`, `bindings` |
| `restart_interpreter` | `setting_id: string`, optional `notebook_id: string \| null = null` | `setting_id`, `name`, `group`, `status` |
| `cancel_paragraph` | `notebook_id: string`, `paragraph_id: string` | `notebook_id`, `paragraph_id` |

Nested result contracts:

- `NotebookTreeNode` contains `notebook_id: string | null`, `name: string`, `path: string`, and
  recursive `children: NotebookTreeNode[]`.
- Paragraph `status` is one of `PENDING`, `RUNNING`, `FINISHED`, `ERROR`, `CANCELLED`, or
  `UNKNOWN`.
- Each paragraph output contains `kind` and `text`; `kind` is one of `TEXT`, `TABLE`, `HTML`,
  `ANGULAR`, or `IMG`. `error` is either null or `{ "message": string }`. `truncated=true`
  means the configured output limit was reached.
- Each interpreter binding contains exactly `setting_id`, `name`, `interpreters: string[]`,
  `selected: boolean`, and `restart_allowed: boolean`. `restart_allowed` reports the local
  allowlist decision; it does not assert upstream authorization or interpreter health.

### Interpreter discovery and restart

Do not treat interpreter restart as a general retry. Use notebook-scoped restart as an explicit three-step workflow:

1. Call `get_interpreter_bindings` with the readable notebook ID.
2. Select an exact binding whose `selected` and `restart_allowed` fields are both true.
3. Call `restart_interpreter` with that `setting_id` and the same `notebook_id`.

Example discovery result:

```json
{
  "notebook_id": "note-1",
  "bindings": [
    {
      "setting_id": "spark_prod",
      "name": "Spark Production",
      "interpreters": ["spark", "sql", "pyspark"],
      "selected": true,
      "restart_allowed": true
    }
  ]
}
```

Example notebook-scoped restart call and result:

```json
{
  "arguments": {
    "setting_id": "spark_prod",
    "notebook_id": "note-1"
  },
  "result": {
    "setting_id": "spark_prod",
    "name": "Spark Production",
    "group": "spark",
    "status": "READY"
  }
}
```

`ZEPPELIN_RESTARTABLE_INTERPRETER_SETTINGS` is a JSON array of exact setting IDs and defaults to
deny. The allowlist is checked before any login, HTTP, ticket, or WebSocket request. Discovery does
not require restart permission and includes locally denied bindings with `restart_allowed=false`.

Omitting `notebook_id`, or passing null, preserves the legacy setting-wide restart. A notebook-mode
failure never drops the notebook context or falls back to setting-wide restart. Neither mode retries
the restart automatically or re-executes paragraphs. Zeppelin may share one interpreter process
across notebooks, so notebook context does not guarantee isolated impact.

The MCP host connection remains local JSON-RPC over stdio. Notebook and paragraph operations use
outgoing Zeppelin HTTP; binding discovery additionally uses an authenticated, bounded outgoing
WebSocket query in the same user session. No MCP HTTP, SSE, or WebSocket listener is opened.

### Zeppelin configuration examples

Equivalent [YAML](docs/examples/zeppelin.yaml) and [JSON](docs/examples/zeppelin.json) examples contain environment variable names under `secrets`, never credentials. Supply paired credentials externally, then launch:

```bash
uv run --locked mcp-stdio --plugin zeppelin --config docs/examples/zeppelin.yaml
```

Environment-only equivalent (credentials remain externally supplied):

```bash
export ZEPPELIN_BASE_URL='https://zeppelin.example.invalid/zeppelin/api'
export ZEPPELIN_REQUEST_TIMEOUT_SECONDS='30'
export ZEPPELIN_ALLOWED_INTERPRETERS='["spark_prod.sql"]'
export ZEPPELIN_RESTARTABLE_INTERPRETER_SETTINGS='["spark_prod"]'
uv run --locked mcp-stdio --plugin zeppelin
```

Execution prefixes and exact restart setting IDs use independent allowlists; both default to deny. All collection overrides (`ALLOWED_INTERPRETERS`, `RESTARTABLE_INTERPRETER_SETTINGS`, `SQL_WRITE_ALLOWED_DATABASES`, `SQL_FORBIDDEN_KEYWORDS`, `SH_ALLOWED_COMMANDS`) use JSON arrays under the `ZEPPELIN_` prefix. Plugin-prefixed overrides take precedence over `MCP_STDIO__SETTINGS__<FIELD>` and file/default values. Startup and tool listing make no network request. Discovery requires a REST base ending in `/api`: only that final component becomes `/ws` (HTTP→WS, HTTPS→WSS), preserving origin and proxy prefix; ambiguous mounts fail before network access.

## DolphinScheduler configuration and tools

The DolphinScheduler plugin supports a versioned YAML or JSON file, or an
environment-only startup. Full non-sensitive examples are available at
[`docs/examples/dolphinscheduler.yaml`](docs/examples/dolphinscheduler.yaml)
and [`docs/examples/dolphinscheduler.json`](docs/examples/dolphinscheduler.json).

For an environment-only process, configure the base URL and optionally a token:

```bash
export DOLPHINSCHEDULER_BASE_URL=http://<ds-host>:12345/dolphinscheduler
export DOLPHINSCHEDULER_TOKEN=<dolphinscheduler-api-token> # optional
uv run mcp-stdio --plugin dolphinscheduler
```

With a configuration file, `secrets.token` contains the environment variable
name `DOLPHINSCHEDULER_TOKEN`, not a token value:

```bash
export DOLPHINSCHEDULER_TOKEN=<dolphinscheduler-api-token>
uv run mcp-stdio --plugin dolphinscheduler \
  --config docs/examples/dolphinscheduler.yaml
```

The process exposes `get_server_status`, `list_objects`, `get_object`,
`search_objects`, `start_workflow`, `get_task_log`, and `extract_log_links`.
`start_workflow` starts a workflow when `dry_run=0`; use `dry_run=1` to request
validation without execution, and obtain user approval before an actual start.
The remaining tools are read-only. Results and task logs are bounded, and the
server does not expose object create, update, delete, pause, resume, or stop
operations.

## Spark event log download

Spark exposes exactly `fetch_spark_event_log(application_id, attempt_id=None, refresh=False)`.
It downloads the configured Spark History Server logs ZIP, validates identities/CRC/JSONL,
redacts credentials and saves local JSONL files plus one manifest for later diagnosis tools.
The first format target is the verified Spark 2.4.7 single-file JSONL layout.

| Input | Default | Meaning |
| --- | --- | --- |
| application_id | required | YARN ID such as `application_1700000000000_0042` |
| attempt_id | null | Exact attempt; omitted requests all available attempt logs |
| refresh | false | Reuse matching saved files; true downloads to a new directory |

Unknown arguments and invalid raw types are rejected without echoing argument values.
Tool arguments cannot specify URLs, output paths, credentials or TLS settings.

| Setting | Default | Meaning |
| --- | --- | --- |
| history_server_url | required | HTTPS root including the gateway mount, without `/api/v1`, credentials or query |
| cache_dir | required | Absolute dedicated local directory; POSIX macOS/Linux |
| verify_tls | true | Set false explicitly to skip certificate and hostname verification |
| knox_sso_url | null | Same-origin HTTPS Knox SSO endpoint, required with username/password |
| ca_bundle_path | null | Optional readable trusted PEM CA for private certificates |
| request_timeout_seconds | 300 | Whole-call budget, including lookup, queueing and processing (maximum 900) |
| max_bytes | 268435456 | Independently bounds ZIP bytes, expanded input and output JSONL totals |

Use [spark.yaml](docs/examples/spark.yaml) or [spark.json](docs/examples/spark.json).
Safely inject an existing login Cookie into `SPARK_GATEWAY_COOKIE`; configuration contains
only its environment-variable name. Anonymous deployments may omit the secret reference.
Verification is enabled by default. For an explicitly trusted self-signed deployment, set
`SPARK_VERIFY_TLS=false` (or YAML `verify_tls: false`) and restart the MCP process.
This disables server identity verification; HTTPS encryption remains. A configured CA is
still validated locally but is not used when verification is disabled. Cookie mode does not log in.

```sh
uv run --locked mcp-stdio --plugin spark --config docs/examples/spark.yaml
```

Environment-only startup uses the same field names with the SPARK prefix:

```sh
export SPARK_HISTORY_SERVER_URL='https://history.example.invalid:8443/gateway/analytics/sparkhistory'
export SPARK_CACHE_DIR='/var/tmp/mcp-spark-l3'
export SPARK_CA_BUNDLE_PATH='/etc/mcp/spark-ca.pem'
# SPARK_GATEWAY_COOKIE is already safely injected; optional overrides:
# SPARK_REQUEST_TIMEOUT_SECONDS and SPARK_MAX_BYTES.
uv run --locked mcp-stdio --plugin spark
```

For Knox username/password authentication, use [spark-basic.yaml](docs/examples/spark-basic.yaml)
or [spark-basic.json](docs/examples/spark-basic.json). Inject `SPARK_USERNAME` and
`SPARK_PASSWORD` through the host's protected environment; do not set `SPARK_GATEWAY_COOKIE`
at the same time. Credentials must be paired, and `SPARK_KNOX_SSO_URL` is required:

```sh
export SPARK_HISTORY_SERVER_URL='https://history.example.invalid:8443/gateway/analytics/sparkhistory'
export SPARK_KNOX_SSO_URL='https://history.example.invalid:8443/gateway/knoxsso/api/v1/websso'
export SPARK_CACHE_DIR='/var/tmp/mcp-spark-l3'
# SPARK_USERNAME and SPARK_PASSWORD are already securely injected.
uv run --locked mcp-stdio --plugin spark
# Or use --config docs/examples/spark-basic.yaml.
```

Before each network download, the adapter sends one empty POST with Basic Authorization to
the configured SSO endpoint and obtains scoped cookies. Only that POST receives the password;
the download GET uses cookies. It never follows redirects or retries failed logins. Both
requests share the call deadline. Cookies stay in memory for that acquisition, are cleared
on all receive exits, and are included in credential redaction before publishing evidence.
Cache hits make no login request. The plugin does not automatically read personal credential
files. This exchange follows [Knox SSO](https://apache.github.io/knox/config_knox_sso/).

For an MCP host, point to the installed release entry point described above and pass the
selected credentials through the host's protected environment:

```json
{
  "mcpServers": {
    "spark": {
      "command": "/absolute/path/to/hive-cli-mcp-stdio-prod/current/venv/bin/mcp-stdio",
      "args": ["--plugin", "spark", "--config", "/absolute/path/to/spark.yaml"]
    }
  }
}
```

Local MCP transport is stdio; outgoing HTTPS is the History Server connection.
Set the host tool timeout above the configured whole-call budget.

The result contains `application_id`, `requested_attempt_id`, `cache_hit`,
`downloaded_at`, `manifest_path` and `files`. Each file contains `attempt_id`,
`local_path`, `spark_version`, `size_bytes`, `sha256`, `source_sha256`,
`event_count` and `application_end_seen`. The two digests describe sanitized output and
original source bytes respectively; ApplicationEnd is not a YARN final status.

JSONL is generated during post-download validation/redaction in a private temporary
directory. After every member passes, the ZIP is removed and the directory is renamed to:

```text
<cache_dir>/<application_id>/all|attempt-<id>/<random-id>/
  eventlog-0001.jsonl
  manifest.json
```

The manifest adds `format_version=1` and the normalized source URL to the result fields,
excluding `cache_hit`. No raw ZIP, unsanitized JSON, index or digest sidecar is retained.
Events retain line order and numeric metrics; credential fields and non-allowlisted
environment properties are redacted. Compressed/rolling logs and malformed tails fail.

Reuse requires the same source URL and exact attempt selection plus verified file hashes.
It preserves the original download time and makes no upstream request, so it does not
guarantee freshness. Refresh saves another directory, preserving previous evidence.
Directories persist until you clean them manually; there is no TTL, deduplication or GC.
One process owns a cache root at a time. Failure/cancellation/shutdown clean owned staging;
a force-killed process may leave ignored `.part-*` directories for manual cleanup.

Live download is opt-in: supply `MCP_STDIO_SPARK_INTEGRATION=1`,
`MCP_STDIO_SPARK_APPLICATION_ID`, optional `MCP_STDIO_SPARK_ATTEMPT_ID`, and the SPARK
URL/cache/CA deployment environment plus either Cookie or paired username/password and SSO URL, then run:

```sh
uv run --locked pytest -m integration tests/integration/test_spark_server.py
```

## Process isolation

Each `mcp-stdio` process loads exactly one plugin. Processes do not share
memory, credentials, connections, live caches, or mutable runtime state. Spark permits sequential
reuse of persistent evidence after the previous cache-directory owner exits. If one
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
