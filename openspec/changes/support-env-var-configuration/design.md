# Design

## Context

The Hive vertical slice already starts successfully from a YAML/JSON `--config`
file, resolves credentials from environment-variable names declared in that
file, and applies `MCP_STDIO__SETTINGS__<FIELD>` generic overrides. Operators
embedding the runner in an MCP host config (e.g. Claude Desktop `mcpServers`)
prefer to pass everything through the host's `env` map and avoid a separate
on-disk file. The original design rejected environment-only configuration
because REST plugins have more non-secret settings; this change reverses that
decision for the Hive slice while keeping the file path fully supported.

## Goals

- `--config` is optional. A process can start from environment variables alone.
- Environment variables have the highest precedence over file values.
- Existing file-based configuration, secret-reference resolution, and
  `MCP_STDIO__SETTINGS__<FIELD>` overrides keep working unchanged.
- No new network access, no new dependencies, no change to stdout/stderr
  discipline, and no change to secret redaction.

## Decisions

### 1. Plugin-owned prefix binding

Each plugin declares a single uppercase prefix (Hive: `HIVE`). The shared config
loader maps `<PREFIX>_<FIELD_UPPER>` to each settings and secrets field of the
plugin's models:

- Settings: `HIVE_HOST`, `HIVE_PORT`, `HIVE_DATABASE`, `HIVE_CACHE_TTL_SECONDS`.
- Secrets: `HIVE_USERNAME`, `HIVE_PASSWORD`.

The prefix is passed into `load_config` as an `env_prefix` parameter; the core
loader never imports a plugin. This keeps the Clean Architecture boundary intact
(core owns loading mechanics, plugins own their field/prefix names).

### 2. Precedence order

For each settings field the effective value is resolved in this order, first
match wins:

1. `<PREFIX>_<FIELD>` environment variable (parsed with the field type adapter).
2. `MCP_STDIO__SETTINGS__<FIELD>` environment variable.
3. File value (when `--config` is supplied).
4. Pydantic model default.

For each secrets field:

1. `<PREFIX>_<FIELD>` environment variable value.
2. The file's secret reference resolved against the environment.
3. Pydantic model default (e.g. `None` for optional secrets).

Because secrets already ultimately come from environment variables, the prefix
binding is consistent in both modes: in file mode it overrides the file's chosen
variable name; in env-only mode it is the only source.

### 3. Optional file path

`load_config` accepts `path: str | Path | None`. When `None`:

- No file is read; `version` defaults to 1 and `plugin` to the `--plugin` value.
- Settings and secrets are synthesized entirely from prefix bindings.
- A required field whose prefix variable is unset raises `CONFIG_ERROR` naming
  the variable (e.g. `HIVE_HOST`), mirroring the existing missing-secret error.
- The same strict model-schema validation (unknown-field rejection, type
  validation, secret-safe errors) runs on the synthesized values.

When `env_prefix` is empty and no path is supplied, startup fails with
`CONFIG_ERROR`, so plugins that have not declared a prefix cannot silently start
with empty configuration.

### 4. CLI change

`--config` becomes optional with default `None`. `--plugin` remains required
(the host always names the selected plugin). `PluginRuntimeBuilder` and
`PluginDefinition.create_runtime` accept `Path | None`.

### 5. Backward compatibility

The `MCP_STDIO__SETTINGS__<FIELD>` override, file loading, safe YAML, and
existing error categories are unchanged. Existing tests and the main spec's
override requirement remain satisfied; only precedence is extended.

## Risks

- Two override mechanisms (`HIVE_*` and `MCP_STDIO__SETTINGS__*`) could confuse
  operators. Mitigation: README documents `<PREFIX>_<FIELD>` as the recommended
  mechanism for env-only startup and states the precedence order explicitly.
- Env-only startup must not weaken secret safety. Mitigation: prefix secret
  values flow through the same `SecretStr` validation and redaction path; error
  messages name variables, never values.
