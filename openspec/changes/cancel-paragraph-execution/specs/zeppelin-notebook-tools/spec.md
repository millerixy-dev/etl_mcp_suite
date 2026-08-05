## MODIFIED Requirements

### Requirement: Expose exactly the Zeppelin notebook lifecycle tools
The Zeppelin plugin SHALL expose exactly `list_notebooks`, `create_notebook`, `add_paragraph`, `run_paragraph`, `get_paragraph_status`, `get_paragraph_result`, `restart_interpreter`, and `cancel_paragraph`.

#### Scenario: List Zeppelin tools
- **WHEN** an MCP client lists tools for a Zeppelin plugin process
- **THEN** the returned tool names are exactly the eight approved Zeppelin tool names

## ADDED Requirements

### Requirement: Cancel paragraph execution
The `cancel_paragraph` tool SHALL accept a `notebook_id` and `paragraph_id` and call `DELETE /api/notebook/job/{notebook_id}/{paragraph_id}` with both identifiers encoded as URL path segments. The tool SHALL return a `CancelParagraphResult` containing `notebook_id` and `paragraph_id` confirming the cancel request was accepted. The tool SHALL NOT return raw HTTP headers, cookies, or unbounded upstream bodies. When the upstream returns a non-200 status, the tool SHALL return an appropriate error category with `notebook_id` and `paragraph_id` as safe identifiers.

#### Scenario: Cancel a running paragraph
- **WHEN** `cancel_paragraph` is called with valid `notebook_id` and `paragraph_id` and the paragraph is running
- **THEN** the tool calls `DELETE /api/notebook/job/{notebook_id}/{paragraph_id}` and returns a result with the `notebook_id` and `paragraph_id`

#### Scenario: Cancel a non-running paragraph
- **WHEN** `cancel_paragraph` is called for a paragraph that is not running and Zeppelin returns 200
- **THEN** the tool returns a result with the `notebook_id` and `paragraph_id` without error

#### Scenario: Reject malformed identifiers before network
- **WHEN** `cancel_paragraph` is called with a `notebook_id` or `paragraph_id` containing a space or slash
- **THEN** the tool returns `INVALID_INPUT` without making a network request

#### Scenario: Report upstream failure
- **WHEN** `cancel_paragraph` is called and Zeppelin returns HTTP 500
- **THEN** the tool returns `UPSTREAM_ERROR` with `notebook_id` and `paragraph_id` as safe identifiers
