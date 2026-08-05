## 1. Core enums and models

- [x] 1.1 Write failing tests: `ToolOperation.RESTART_INTERPRETER` exists and its identifier set is `{"setting_id"}`; `RestartInterpreterResult` is a frozen model with `setting_id`, `name`, `group`, `status` fields. Confirm RED.
- [x] 1.2 Add `RESTART_INTERPRETER` to `ToolOperation` + identifier set in `errors.py`; add `RestartInterpreterResult` to `models.py`. Confirm GREEN.

## 2. Configuration

- [x] 2.1 Write failing tests: `restartable_interpreter_settings` defaults to empty tuple; env `ZEPPELIN_RESTARTABLE_INTERPRETER_SETTINGS` overrides; malformed/duplicate entries rejected; unknown fields rejected. Confirm RED.
- [x] 2.2 Add `restartable_interpreter_settings` field + validator to `ZeppelinSettings` in `config.py`. Confirm GREEN.

## 3. Gateway and HTTP client

- [x] 3.1 Write failing tests: `ZeppelinGateway` protocol has `restart_interpreter(setting_id)` method; `ZeppelinHttpClient.restart_interpreter` calls `PUT /api/interpreter/setting/restart/{setting_id}`, extracts `id`/`name`/`group`/`status` from response, discards other fields; maps 500 to `UPSTREAM_ERROR`. Confirm RED.
- [x] 3.2 Add `restart_interpreter` to `ZeppelinGateway` protocol (`gateway.py`) and implement in `ZeppelinHttpClient` (`http_client.py`) using `encode_opaque_id` for path encoding + bounded response parsing. Confirm GREEN.

## 4. Application service

- [x] 4.1 Write failing tests: `restart_interpreter` rejects non-allowlisted setting ID with `INVALID_INPUT` before network; rejects malformed setting ID; allowlisted setting ID calls gateway and returns `RestartInterpreterResult`. Confirm RED.
- [x] 4.2 Implement `restart_interpreter` in `ZeppelinNotebookService` with allowlist gate + `validate_interpreter_name` for setting ID. Confirm GREEN.

## 5. Tool adapter and contract

- [x] 5.1 Write failing tests: `restart_interpreter` tool is registered with `setting_id` input; contract test asserts exactly 7 Zeppelin tool names. Confirm RED.
- [x] 5.2 Register `restart_interpreter` tool in `ZeppelinToolAdapter`; update tool-count contract test. Confirm GREEN.

## 6. Final verification

- [x] 6.1 Run full unit + contract suite, `ruff check`, `pyright`, `openspec validate --changes`, `openspec validate --specs`; all green.
