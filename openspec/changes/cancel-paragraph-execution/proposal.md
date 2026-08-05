## Why

When a paragraph runs too long (e.g., a Spark job stuck on a large shuffle), the agent has no way to stop it. The only recovery path is to wait for timeout or ask a human to intervene via the Zeppelin UI. Zeppelin 0.10.1 exposes `DELETE /api/notebook/job/{notebookId}/{paragraphId}` which is accessible to regular users and cancels a running paragraph. Adding a `cancel_paragraph` tool closes this gap and enables autonomous recovery from runaway executions.

## What Changes

- Add a `cancel_paragraph` tool that accepts `notebook_id` and `paragraph_id` and calls `DELETE /api/notebook/job/{notebookId}/{paragraphId}`.
- Return a `CancelParagraphResult` containing `notebook_id` and `paragraph_id`, confirming the cancel request was accepted by Zeppelin. The agent polls `get_paragraph_status` afterwards to observe the final status.
- Expand the tool set from seven to eight tools.

## Capabilities

### New Capabilities
<!-- None - this change extends an existing capability. -->

### Modified Capabilities
- `zeppelin-notebook-tools`: the tool-set requirement expands to include `cancel_paragraph`; a new requirement defines the cancel tool's contract.

## Impact

- `src/mcp_stdio/core/errors.py` - new `ToolOperation.CANCEL_PARAGRAPH` enum value + identifier set.
- `src/mcp_stdio/plugins/zeppelin/models.py` - new `CancelParagraphResult` model.
- `src/mcp_stdio/plugins/zeppelin/gateway.py` - new `cancel_paragraph` method on the protocol.
- `src/mcp_stdio/plugins/zeppelin/http_client.py` - implement `DELETE /api/notebook/job/{notebookId}/{paragraphId}`.
- `src/mcp_stdio/plugins/zeppelin/service.py` - new `cancel_paragraph` use case.
- `src/mcp_stdio/plugins/zeppelin/tools.py` - register `cancel_paragraph` tool.
- `src/mcp_stdio/plugins/zeppelin/plugin.py` - no change (service constructor signature unchanged).
- Tests: new unit tests for gateway, service, models, tools; updated contract tests for tool count.
