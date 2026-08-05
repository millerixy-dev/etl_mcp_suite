## Why

When SparkContext stops (OOM, resource contention, idle timeout), the agent's `add_paragraph -> run_paragraph -> get_paragraph_result` loop breaks with no recovery path. The agent cannot restart the interpreter and must escalate to a human. Zeppelin 0.10.1 exposes `PUT /api/interpreter/setting/restart/{settingId}` which is accessible to regular (non-admin) users and returns the interpreter setting with a `READY` status. Adding a `restart_interpreter` tool closes the autonomous recovery gap.

## What Changes

- Add a `restart_interpreter` tool that accepts an interpreter setting ID (the interpreter group name, e.g. `spark`, `sh`) and calls `PUT /api/interpreter/setting/restart/{settingId}`. The agent derives the setting ID from the paragraph shebang (`%spark` -> `spark`, `%spark.sql` -> `spark`).
- Add a `restartable_interpreter_settings` configuration field (env `ZEPPELIN_RESTARTABLE_INTERPRETER_SETTINGS`) that defaults to an empty sequence (deny all). Only setting IDs in this allowlist may be restarted.
- Return a bounded `RestartInterpreterResult` containing `setting_id`, `name`, `group`, and `status` from the upstream response. The tool SHALL NOT return raw properties, dependencies, stack traces, or unbounded upstream bodies.
- Expand the tool set from six to seven tools.

## Capabilities

### New Capabilities
<!-- None - this change extends an existing capability. -->

### Modified Capabilities
- `zeppelin-notebook-tools`: the tool-set requirement expands to include `restart_interpreter`; the configuration requirement gains `restartable_interpreter_settings`; a new requirement defines the restart tool's contract and safety gate.

## Impact

- `src/mcp_stdio/plugins/zeppelin/gateway.py` - new `restart_interpreter` method on the `ZeppelinGateway` protocol.
- `src/mcp_stdio/plugins/zeppelin/http_client.py` - implement `PUT /api/interpreter/setting/restart/{settingId}` with bounded response parsing.
- `src/mcp_stdio/plugins/zeppelin/models.py` - new `RestartInterpreterResult` model + setting-ID validation.
- `src/mcp_stdio/plugins/zeppelin/service.py` - new `restart_interpreter` use case with allowlist gate.
- `src/mcp_stdio/plugins/zeppelin/config.py` - new `restartable_interpreter_settings` field + validator.
- `src/mcp_stdio/plugins/zeppelin/tools.py` - register `restart_interpreter` tool.
- `src/mcp_stdio/core/errors.py` - new `ToolOperation.RESTART_INTERPRETER` enum value + identifier set.
- Tests: new unit tests for gateway, service, config, models, tools; updated contract tests for tool count.
