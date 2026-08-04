## Why

When the Zeppelin write-safety gate rejects a paragraph, the MCP tool error only carries the stable category `INVALID_INPUT` and the fixed message "The request input is invalid." The specific cause - which rule fired (interpreter allowlist, forbidden-keyword blacklist, write-target database allowlist, or sh command allowlist) and which safe identifier was involved - is discarded by the service. Downstream agents cannot distinguish a blacklist hit from a whitelist hit and must guess, which leads to unproductive retry strategies (e.g. creating a new notebook instead of retargeting the database).

## What Changes

- Add an optional, safe `explanation` field to the shared `ToolError` model. It carries a concise rejection reason with safe identifiers only (no credentials, stack traces, or raw upstream bodies). The stable per-category `message` is unchanged; `explanation` is additive and defaults to absent for backward compatibility.
- Make Zeppelin write-safety rejections produce a specific explanation naming the rule and the safe identifier: interpreter name, SQL keyword, target database, or sh command.
- Propagate the rejection reason from the service into the `ToolError.explanation` so the serialized MCP tool error tells the caller exactly which gate fired and why.

## Capabilities

### New Capabilities
<!-- None - this change extends existing error and gating behavior. -->

### Modified Capabilities
- `plugin-stdio-runtime`: the safe-stable-tool-errors requirement gains an optional concise `explanation` field carrying safe identifiers.
- `zeppelin-notebook-tools`: the write-safety-gate requirement requires rejections to include a concise explanation naming the fired rule and the safe identifier.

## Impact

- `src/mcp_stdio/core/errors.py` - `ToolError` gains an optional `explanation` field; `to_dict` emits it when present.
- `src/mcp_stdio/plugins/zeppelin/models.py` - safety-gate validators produce specific messages with safe identifiers.
- `src/mcp_stdio/plugins/zeppelin/safety.py` - `InterpreterAllowlistChecker` message names the interpreter.
- `src/mcp_stdio/plugins/zeppelin/service.py` - captures the rejection reason and passes it as the `explanation`.
- Tests: core error tests, zeppelin model/safety/service tests updated; contract tests for the serialized error shape.
