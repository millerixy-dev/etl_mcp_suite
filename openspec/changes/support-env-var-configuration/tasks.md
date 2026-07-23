## 1. OpenSpec Artifacts

- [x] 1.1 Create the `support-env-var-configuration` change with proposal, spec delta, design, and tasks; validate with `openspec validate`.

## 2. Configuration Loader

- [x] 2.1 Add failing tests for environment-variable-only startup (no path, prefix bindings supply all settings and secrets) and for missing required prefix variables naming the variable.
- [x] 2.2 Add failing tests for prefix override precedence: `<PREFIX>_<FIELD>` wins over `MCP_STDIO__SETTINGS__<FIELD>` and over file values, for both settings and secrets.
- [x] 2.3 Implement optional `path`, `env_prefix` parameter, prefix override helpers, and required-variable checks in `load_config` until tests pass.
- [x] 2.4 Confirm existing file-based, generic-override, and secret-reference tests stay green.

## 3. Bootstrap and Plugin Wiring

- [x] 3.1 Add failing tests that `--config` is optional and that env-only `construct_runtime` builds a Hive runtime without network access.
- [x] 3.2 Make `--config` optional in `parse_args`, update `PluginRuntimeBuilder`/`create_runtime` to accept `Path | None`, pass `env_prefix="HIVE"` from the Hive plugin.
- [x] 3.3 Add a subprocess smoke test that starts the Hive process with environment variables only (no `--config`) and lists the exact tool set.

## 4. Documentation

- [x] 4.1 Update README, `docs/examples/hive.yaml`/`hive.json`, and architecture docs to document the optional `--config`, the `<PREFIX>_<FIELD>` convention, the precedence order, and an MCP host `env`-only example.

## 5. Verification

- [x] 5.1 Run the full unit/contract suite, Ruff, Pyright, wheel build, console-entry-point smoke test, and strict OpenSpec validation; report exact commands and results.
