## Why

The Zeppelin MCP can restart an explicitly supplied, allowlisted setting, but an ordinary user has no MCP tool to discover the setting IDs displayed by the notebook UI. Investigation of the deployed frontend confirmed that the UI discovers these through authenticated WebSocket `GET_INTERPRETER_BINDINGS`, then calls the restart REST endpoint with `noteId`; the current MCP implements neither the discovery step nor that notebook context.

## What Changes

- Add `get_interpreter_bindings(notebook_id)`, returning a bounded, sanitized list of setting IDs, setting names, interpreter names, selection flags, and the local restart-allowlist decision.
- Use Zeppelin's authenticated, notebook-oriented WebSocket query instead of the administrator-only settings REST enumeration. Obtain session ticket metadata internally and keep it out of MCP arguments, results, configuration, logs, and fixtures.
- Extend `restart_interpreter(setting_id, notebook_id=None)`: when a notebook is provided, verify access and current binding membership, then send `{"noteId": notebook_id}` to the existing PUT endpoint. Omission preserves the existing explicit setting-wide operation; there is never an automatic fallback from notebook mode to setting-wide mode.
- Preserve the restart allowlist as a mandatory, default-deny gate checked before network access. Treat IDs as upstream identifiers, not interpreter group names; admit bounded opaque IDs, including numeric-leading IDs, in both tool input and allowlist configuration.
- Bound WebSocket message size, cumulative received bytes, waiting, concurrency, and cleanup. Add one direct WebSocket dependency; keep the MCP host transport as stdio.
- Update exact tool-set contracts from eight to nine tools, architecture views, usage/configuration examples, and the agent-neutral Zeppelin skill.

## Non-Goals

- No interpreter creation, editing, binding changes, settings-wide enumeration, administrator credentials, or privilege escalation.
- No automatic restart, automatic execution retry, or automatic re-execution of paragraphs after restart.
- No guarantee that notebook context isolates a shared interpreter process; deployment sharing settings remain authoritative.
- No persistent WebSocket subscriber, cache of bindings, new MCP network listener, HTTP/SSE MCP transport, or WebSocket support in other plugins.
- No removal of the existing setting-only restart interface and no broad refactoring of unrelated HTTP tools.

## Capabilities

### New Capabilities

None; this change extends the Zeppelin capability already defined by active changes.

### Modified Capabilities

- `zeppelin-notebook-tools`: add notebook binding discovery, specify its authenticated and bounded upstream lifecycle, extend restart with notebook context, correct ID validation, and update the exact tool set. This capability currently resides in active changes rather than `openspec/specs/`; this delta builds on `deliver-zeppelin-plugin-slice`, `support-interpreter-restart`, `cancel-paragraph-execution`, and the subsequent safety/configuration changes. Their unchanged requirements remain in force.

## Impact

- Existing Zeppelin modules: `config.py`, `models.py`, `gateway.py`, `service.py`, `http_client.py`, `tools.py`, and `plugin.py`; a proposed plugin-local `websocket_client.py` will isolate WebSocket infrastructure. Shared changes are limited to the operation enum and safe identifier mapping in `core/errors.py`.
- Add `websockets>=15,<16` as a direct dependency in `pyproject.toml`, resolved through `uv.lock`, preserving Python 3.10 compatibility. No dependency change is made during proposal creation.
- Tests: configuration, models, service fakes, HTTP mock transports, injected WebSocket fakes, plugin/tool schemas, stdout/secret discipline, architecture boundaries, and explicitly opt-in live verification.
- Documentation: README, new Zeppelin YAML/JSON examples, both architecture documents, and `skills/zeppelin/SKILL.md`; the tool-count test for that skill must follow the nine-tool contract.
- Compatibility: existing setting-only calls and the four-field restart result remain supported. Notebook mode fails closed on discovery/authentication/membership failure. `restart_allowed` describes local policy, not a promise of upstream permission or successful execution.
- Evidence: the deployed frontend bundle inspected on 2026-09-10 (`app.452e77a4c556c7861195.js`) matches the relevant [Zeppelin 0.10.1 notebook controller](https://github.com/apache/zeppelin/blob/v0.10.1/zeppelin-web/src/app/notebook/notebook.controller.js#L599) and [WebSocket message service](https://github.com/apache/zeppelin/blob/v0.10.1/zeppelin-web/src/components/websocket/websocket-message.service.js#L353). The restart button was not pressed, and no authenticated discovery or live restart was executed in this investigation.
