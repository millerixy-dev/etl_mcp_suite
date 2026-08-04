# Design

## Context

The shared `ToolError` carries a fixed per-category `message` (e.g. "The request input is invalid.") and a constrained `identifiers` map. There is no channel for a specific rejection reason. The Zeppelin write-safety gate raises `ValueError` with a safe, fixed message, but the service discards it (`except ValueError: raise _invalid_input(...)`), so the MCP client only sees the generic category message and cannot tell which gate fired.

## Goals / Non-Goals

**Goals:**
- Add a safe, optional `explanation` channel to `ToolError` so rejections can name their cause.
- Make Zeppelin write-safety rejections name the fired rule and the safe identifier.
- Keep the stable `message` fixed per category; `explanation` is additive and absent by default.

**Non-Goals:**
- Changing the error categories or the constrained `identifiers` allow-list.
- Exposing stack traces, credentials, raw bodies, or rejected input beyond safe identifiers.
- Explanations for non-safety `INVALID_INPUT` causes (input-format validation keeps its fixed messages, though they may surface as explanations too since they are safe).

## Decisions

### 1. Add optional `explanation` to `ToolError`

`ToolError` gains `explanation: str | None = None` (init field). `to_dict` emits `"explanation"` only when it is a non-empty string. `ToolError.create` accepts an optional `explanation`. The field is unstructured text (not an enum) because rejection causes are plugin-specific; safety is enforced at the call sites (only safe identifiers are interpolated). The fixed `message` is unchanged.

### 2. Specific, safe rejection messages

The safety-gate validators and checkers interpolate only safe identifiers into the explanation:

- `validate_sql_forbidden_keywords`: `sql keyword 'DROP' is forbidden by the blacklist`
- `validate_sql_write_target`: `sql write target database 'other_db' is not allowlisted` (and `cannot be determined` when the `db.table` form is missing)
- `validate_sh_command`: `sh command 'rm' is not allowlisted`
- `InterpreterAllowlistChecker`: `interpreter 'spark' is not allowlisted`

Database names, SQL keywords, interpreter names, and command names are safe identifiers per the project error policy; the paragraph body and credentials are never interpolated.

### 3. Propagation through the service

`add_paragraph` captures the `ValueError` text as the `explanation` and passes it to `ToolError.create`. The missing-shebang path (`intr is None`) gets an explicit explanation. Other service methods are unchanged (their `INVALID_INPUT` causes are input-format validation with safe fixed messages; surfacing those is harmless and consistent).

### 4. Serialization

`tools.py` already serializes `error.to_dict(...)` into the `FastMCPToolError`; once `to_dict` emits `explanation`, no tool-adapter change is needed. The explanation appears alongside the existing category/message/identifiers/correlation_id.

## Risks / Trade-offs

- [Free-text explanation could leak unsafe detail] -> Mitigated: only safe identifiers are interpolated by the validators; the `message` and `identifiers` channels remain constrained; the explanation is produced by trusted validator code, not caller input.
- [Explanation text is not contract-stable like categories] -> Accepted: the `category` remains the stable contract; `explanation` is diagnostic and may evolve. Clients should branch on `category`, not parse `explanation`.
