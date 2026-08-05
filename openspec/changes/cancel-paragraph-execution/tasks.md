## 1. Core enums and models

- [x] 1.1 Write failing tests: `ToolOperation.CANCEL_PARAGRAPH` exists with identifier set `{"notebook_id", "paragraph_id"}`; `CancelParagraphResult` is a frozen model with `notebook_id` and `paragraph_id`. Confirm RED.
- [x] 1.2 Add `CANCEL_PARAGRAPH` to `ToolOperation` + identifier set in `errors.py`; add `CancelParagraphResult` to `models.py`. Confirm GREEN.

## 2. Gateway and HTTP client

- [x] 2.1 Write failing tests: `ZeppelinHttpClient.cancel_paragraph` calls `DELETE /api/notebook/job/{notebook_id}/{paragraph_id}`, returns `CancelParagraphResult`; maps >= 400 to error. Confirm RED.
- [x] 2.2 Add `cancel_paragraph` to `ZeppelinGateway` protocol + implement in `ZeppelinHttpClient`. Confirm GREEN.

## 3. Application service and tool adapter

- [x] 3.1 Write failing tests: service `cancel_paragraph` validates IDs, calls gateway, returns result; tool adapter registers `cancel_paragraph` with `notebook_id` + `paragraph_id` params; contract test asserts exactly 8 tool names. Confirm RED.
- [x] 3.2 Implement `cancel_paragraph` in service + register tool in adapter + update contract tests. Confirm GREEN.

## 4. Final verification

- [x] 4.1 Run full unit + contract suite, `ruff check`, `pyright`, `openspec validate --changes`, `openspec validate --specs`; all green.
