## 1. Local pagination regression

- [ ] 1.1 Write and run a failing service test showing that an unpaginated project or workflow collection is sliced by 1-based `page_no` and effective `page_size`, preserves `total_count`, returns an empty out-of-range page, and marks only `max_detail_items` trimming as `truncated`.
- [ ] 1.2 Implement the smallest service-only pagination change; rerun the focused test and refactor only after it is green.

## 2. Task-instance response compatibility

- [ ] 2.1 Write and run failing mock-transport adapter tests for the DolphinScheduler 3.1.7 `data.taskList` wrapper and for missing/non-array `taskList` rejection without raw-response disclosure.
- [ ] 2.2 Implement the smallest endpoint-specific adapter parser change; rerun the focused adapter tests and refactor only after they are green.

## 3. Verification

- [ ] 3.1 Run the focused DolphinScheduler service, HTTP adapter, MCP contract, architecture, and opt-in integration test selections; report unavailable live verification as skipped.
- [ ] 3.2 Run the full locked test suite, Ruff, Pyright, console-entry-point smoke test, `openspec validate --changes`, and `openspec validate --specs`; only then mark the completed tasks.
