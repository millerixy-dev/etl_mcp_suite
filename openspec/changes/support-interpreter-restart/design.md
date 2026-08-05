## Context

When SparkContext stops, the agent cannot recover autonomously. Zeppelin 0.10.1 exposes `PUT /api/interpreter/setting/restart/{settingId}` which is accessible to regular (non-admin) users and returns the interpreter setting with a `READY` status. The `GET /api/interpreter` list endpoint is admin-only (401 for regular users), so a `list_interpreters` tool is not feasible without admin credentials. The agent derives the setting ID from the paragraph shebang (`%spark` -> `spark`, `%spark.sql` -> `spark`).

**Verified API behavior (Zeppelin 0.10.1, user `liji`, non-admin):**

| Endpoint | Method | Result |
|---|---|---|
| `/api/interpreter/setting/restart/{settingId}` | PUT | 200 OK, returns full setting object |
| `/api/interpreter/setting/restart/{settingId}` | POST | 405 Method Not Allowed |
| `/api/interpreter` | GET | 401 admin-only |
| `/api/interpreter/setting/restart/{nonexistent}` | PUT | 500 NullPointerException |

The restart response body contains: `id`, `name`, `group`, `status` (`READY` after restart), `interpreterGroup` (list of sub-interpreters), `option`, `properties`, `dependencies`. Only `id`, `name`, `group`, `status` are safe to return; the rest may contain sensitive config or unbounded data.

## Goals / Non-Goals

**Goals:**
- Enable autonomous recovery from interpreter failures (SparkContext stopped, etc.).
- Gate restart behind an explicit allowlist (default deny) to prevent unintended blast radius.
- Return only safe, bounded fields from the upstream response.
- Work with regular (non-admin) Zeppelin credentials.

**Non-Goals:**
- Listing interpreters (GET API is admin-only; not feasible for regular users).
- Per-notebook interpreter binding management (endpoint returns 404 in this deployment).
- Restarting specific sub-interpreters (only group-level restart is supported).
- Auto-detecting interpreter failure and auto-restarting (the agent decides when to restart).

## Decisions

### D1: Single tool `restart_interpreter(setting_id)`

No `list_interpreters` tool - the GET API is admin-only. The agent derives the setting ID from the paragraph shebang (group name = part before the first dot, or the whole name). The config allowlist tells the agent which settings can be restarted.

**Alternatives considered:**
- `list_interpreters` + `restart_interpreter`: rejected because GET `/api/interpreter` is admin-only (401).
- `get_interpreter_status` + `restart_interpreter`: rejected because there is no non-admin status endpoint; the restart response itself includes `status: READY`.

### D2: `PUT` method (not POST)

Zeppelin 0.10.1 accepts only `PUT` for the restart endpoint. POST returns 405. The existing `_request` helper supports arbitrary methods, so no infrastructure change is needed.

### D3: Allowlist gate in the service layer (not the safety hook)

The restart allowlist is checked in `ZeppelinNotebookService.restart_interpreter` before calling the gateway, returning `INVALID_INPUT` when the setting ID is not in `restartable_interpreter_settings`. This is input validation, not paragraph content gating, so it belongs in the service, not in `ParagraphSafetyHook`.

### D4: Bounded result model

`RestartInterpreterResult` is a frozen Pydantic model with exactly four fields: `setting_id: str`, `name: str`, `group: str`, `status: str`. The HTTP adapter extracts these from the upstream response and discards `properties`, `dependencies`, `option`, `interpreterGroup`, and any other fields.

### D5: Setting ID validation reuses the interpreter name pattern

`setting_id` MUST match `[A-Za-z][A-Za-z0-9_.-]{0,63}` (same as `allowed_interpreters`). It is URL-path-encoded using the existing `encode_opaque_id` pattern (validate then percent-encode). This prevents path injection.

### D6: Error mapping

| Upstream status | Error category | Safe identifier |
|---|---|---|
| 401 / 403 | `AUTHENTICATION_FAILED` | `setting_id` |
| 404 | `UPSTREAM_ERROR` | `setting_id` |
| 500 (nonexistent setting) | `UPSTREAM_ERROR` | `setting_id` |
| >= 400 other | `UPSTREAM_ERROR` | `setting_id` |
| Connect/Read timeout | `TIMEOUT` | `setting_id` |
| Connection error | `CONNECTION_FAILED` | `setting_id` |

The existing `_request` method already handles 401/403, >= 400, and transport errors. The 500 case (nonexistent setting ID causing NPE) maps to `UPSTREAM_ERROR` through the existing >= 400 path.

## Risks / Trade-offs

- **[Blast radius]** Restarting an interpreter setting affects all notebooks using that interpreter, not just the current one. -> **Mitigation**: the `restartable_interpreter_settings` allowlist defaults to empty (deny all); operators must explicitly opt in.
- **[No status check]** The agent cannot check interpreter status without restarting it (no non-admin GET endpoint). -> **Mitigation**: the restart response includes `status: READY`, confirming the restart succeeded. The agent infers failure from paragraph execution errors.
- **[500 for nonexistent setting]** Zeppelin returns 500 NPE for unknown setting IDs rather than 404. -> **Mitigation**: the service validates the setting ID format before calling the gateway; the allowlist further restricts to known settings. The 500 is mapped to `UPSTREAM_ERROR` with the setting ID as a safe identifier.

## Migration Plan

1. Add `restartable_interpreter_settings` to `ZeppelinSettings` (default empty).
2. Add `RestartInterpreterResult` model.
3. Add `restart_interpreter` to `ZeppelinGateway` protocol + `ZeppelinHttpClient`.
4. Add `restart_interpreter` use case to `ZeppelinNotebookService`.
5. Add `RESTART_INTERPRETER` to `ToolOperation` enum + identifier set.
6. Register `restart_interpreter` tool in `ZeppelinToolAdapter`.
7. No breaking changes to existing tools; the new tool is additive.

## Open Questions

- None. The API has been verified against the live Zeppelin 0.10.1 instance.
