## Context

When a paragraph runs too long, the agent cannot stop it. Zeppelin 0.10.1 exposes `DELETE /api/notebook/job/{notebookId}/{paragraphId}` which is accessible to regular (non-admin) users and cancels a running paragraph. This is the same path used by `run_paragraph` (which uses POST), just with a different HTTP method. Verified against the live instance: `DELETE` returns `{"status":"OK"}` with no body content.

## Goals / Non-Goals

**Goals:**
- Enable autonomous recovery from runaway paragraph executions.
- Return a bounded result confirming the cancel was accepted.

**Non-Goals:**
- Waiting for the paragraph to reach a terminal status (the agent polls `get_paragraph_status` afterwards).
- Batch cancellation of multiple paragraphs.
- Cancelling all paragraphs in a notebook.

## Decisions

### D1: DELETE method on the job endpoint

`DELETE /api/notebook/job/{notebookId}/{paragraphId}` is the Zeppelin 0.10.1 cancel endpoint. It uses the same path as `run_paragraph` (POST), differing only in HTTP method. The existing `_request_json` helper supports arbitrary methods.

### D2: No new configuration

Cancel is a safe, idempotent operation (cancelling a non-running paragraph returns 200). No allowlist or safety gate is needed, unlike `restart_interpreter` which has blast radius.

### D3: Bounded result with no status field

The DELETE response is `{"status":"OK"}` with no paragraph status. `CancelParagraphResult` contains only `notebook_id` and `paragraph_id`. The agent polls `get_paragraph_status` to observe the final status (CANCELLED/ABORTED).

## Risks / Trade-offs

- **[No status in response]** The cancel response does not include the paragraph's new status. -> **Mitigation**: the agent calls `get_paragraph_status` after cancel to confirm the transition. This is consistent with the `run_paragraph` pattern which returns `PENDING` without waiting.
- **[Cancel non-running paragraph]** Cancelling a paragraph that is not running returns 200 (idempotent). -> **Mitigation**: this is safe and matches Zeppelin's behavior; no special handling needed.

## Migration Plan

1. Add `CANCEL_PARAGRAPH` to `ToolOperation` + identifier set.
2. Add `CancelParagraphResult` model.
3. Add `cancel_paragraph` to gateway protocol + HTTP client.
4. Add `cancel_paragraph` use case to service.
5. Register `cancel_paragraph` tool.
6. No config or plugin.py changes; no breaking changes.

## Open Questions

- None. The API has been verified against the live Zeppelin 0.10.1 instance.
