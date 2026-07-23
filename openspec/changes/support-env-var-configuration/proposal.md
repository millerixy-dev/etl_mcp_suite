## Why

MCP host configuration files (for example Claude Desktop's `mcpServers` JSON) pass
process arguments and an `env` map. Requiring a separate `--config` file forces
operators to maintain an extra on-disk YAML/JSON file alongside the MCP host
config, which is friction for single-plugin local setups and a deployment hazard
on locked-down machines where writing config files is restricted. The current
runtime already resolves credentials from environment variables; extending the
same model to all settings lets a host start a plugin process with zero config
files.

## What Changes

- Make the `--config` CLI argument optional so a plugin process can start from
  environment variables alone.
- Add a plugin-owned environment-variable binding convention: each plugin
  declares a `<PREFIX>` and the loader maps `<PREFIX>_<FIELD>` to its settings
  and secrets fields (for example `HIVE_HOST`, `HIVE_USERNAME`).
- Give environment variables the highest precedence: when a `--config` file is
  also supplied, `<PREFIX>_<FIELD>` values override file values for both
  settings and secrets.
- Keep the existing `MCP_STDIO__SETTINGS__<FIELD>` generic override working at a
  lower precedence, preserving backward compatibility.
- Apply the same strict validation, secret redaction, fail-closed behavior, and
  no-network-during-startup guarantees to the environment-variable-only path.

## Capabilities

### Modified Capabilities

- `plugin-stdio-runtime`: configuration loading accepts an optional file and a
  plugin-prefix environment-variable source with highest precedence.
