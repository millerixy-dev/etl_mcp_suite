# Task 4.1 verification evidence

## Local real-snapshot scale check

Executed `uv run --locked python` using the existing saved private manifests and `SparkEventLogAdapter` only for exclusive directory ownership. Called the local `SparkInspectionAdapter.inspect/query` with the exact selected attempt and verified output digest/event counts against each manifest. No credentials or authentication configuration were read and no upstream request was made.

| Application / attempt | JSONL bytes | Events | TaskEnd matches | Inspect seconds | Query seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| application_1783000588461_681757 / 1 | 4008504 | 2094 | 1002 | 0.072 | 0.086 |
| application_1783000588461_687089 / 2 | 6205392 | 3474 | 1700 | 0.146 | 0.117 |

Both samples had ApplicationEnd and no observed failure signals. Process peak was 44.72 MiB on macOS, including interpreter and imported dependencies; this is not incremental parser memory. Query selected all matching TaskEnd records for counting but returned only one record. Network requests: zero. These are 4 MB and 6 MB success samples; they do not verify a 100 MB maximum, failure diagnosis, real authentication, or a deployed MCP host.

Five synthetic diagnostic cases were exercised separately through actual in-process MCP dispatch and manually evaluated in task-3.2-report.md. Real stdio transport and offline restart are covered by the contract suite; actual live-backend integration is not executed.

## Final verification

The controller will append actual integrated command/review results below before gating task 4.1.

### Core error-operation contract correction

The closed public operation assertion in `tests/unit/core/test_errors.py` lagged the two approved inspection tools. `ToolOperation` and the Spark capability spec already include `inspect_spark_event_log` and `query_spark_events`; no production behavior changed.

- RED: `UV_NO_EDITABLE=1 uv run --locked pytest tests/unit/core/test_errors.py::test_tool_operations_are_closed_to_v1_tools_plus_internal_fallback` failed (1 failed), with precisely those two names extra in the actual set.
- GREEN: after adding the two names to the exact expected set, `UV_NO_EDITABLE=1 uv run --locked pytest tests/unit/core/test_errors.py` passed (45 passed in 0.12s).
