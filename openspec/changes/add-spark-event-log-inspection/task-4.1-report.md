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

Integrated verification was executed on the final implementation and the corrected core operation test. Results and the local environment adjustment are recorded below.

### Core error-operation contract correction

The closed public operation assertion in `tests/unit/core/test_errors.py` lagged the two approved inspection tools. `ToolOperation` and the Spark capability spec already include `inspect_spark_event_log` and `query_spark_events`; no production behavior changed.

- RED: `UV_NO_EDITABLE=1 uv run --locked pytest tests/unit/core/test_errors.py::test_tool_operations_are_closed_to_v1_tools_plus_internal_fallback` failed (1 failed), with precisely those two names extra in the actual set.
- GREEN: after adding the two names to the exact expected set, `UV_NO_EDITABLE=1 uv run --locked pytest tests/unit/core/test_errors.py` passed (45 passed in 0.12s).

### Integrated command results

| Command | Actual result |
| --- | --- |
| `uv sync --locked` | 57 packages resolved, 51 checked; no dependency or lock edits |
| `uv sync --locked --no-editable` | Same current project installed as a regular package; local verification environment only |
| `UV_NO_EDITABLE=1 uv run --locked pytest` | 1806 passed, 6 skipped, 6 deselected in 29.77 s |
| `uv run --locked --no-editable ruff check .` | All checks passed |
| `UV_NO_EDITABLE=1 uv run --locked pyright` | 0 errors, 0 warnings, 0 informations; updater notice only |
| `uv build` | Built wheel and source distribution successfully |
| `UV_NO_EDITABLE=1 uv run --locked mcp-stdio --help` | Exit 0; four-plugin console help displayed without upstream access |
| `openspec validate add-spark-event-log-inspection --strict` | Valid |
| `openspec validate --changes --strict` | 16 passed, 0 failed |
| `openspec validate --specs --strict` | 2 passed, 0 failed |
| `git diff --check` | Exit 0 |

The initial full run had 1799 passed, one stale exact-operation assertion failure and six subprocess import failures. The assertion correction follows the RED/GREEN evidence above. The six import failures and initial console smoke failure reproduced the previously diagnosed macOS environment issue: the editable .pth carried UF_HIDDEN and Python site initialization skipped it. Clearing that flag restored the import within one process, but the flag reappeared before later child processes. Installing the same project via uv's non-editable mode removed the .pth dependency. The focused registry suite then passed (14 tests in 2.59 s), followed by the complete green rerun above. No PYTHONPATH, source, lockfile or production configuration workaround was added.

The default suite excludes tests marked integration (six deselected), and six opt-in DolphinScheduler cases skipped because integration was not enabled. No live-backend integration was executed or claimed. Strict validation also emitted existing informational notices about unrelated archive ordering and a long main-spec requirement; all validations passed.

### Whole-change review

A separate read-only reviewer examined the capability range `cd8abb0..17a21f7`, its active design/spec/tasks, relevant unchanged cache/redaction/runtime code, tests and task reports. The verdict was ready after the controller records final passing verification, with no Critical, Important or Minor findings. It confirmed snapshot verification, direct filtering and pagination, cleanup, public redaction, architecture boundaries, documentation and the evidence-loop Skill. The reviewer also checked the final narrow test-contract correction in `5b73fdc` and approved it without findings. No additional feature, dependency, index, state file or broad refactor was recommended.
