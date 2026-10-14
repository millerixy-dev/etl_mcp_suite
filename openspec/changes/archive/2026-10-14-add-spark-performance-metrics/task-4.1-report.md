# Task 4.1 verification evidence

OpenSpec tasks.md remains the controller-owned acceptance checklist. The controller completed final integrated verification after task 3.2; the independent whole-change review found no actionable issue. Evidence below records executed checks and their limits.

## Local real-snapshot check

Executed `UV_NO_EDITABLE=1 uv run --locked --no-sync python` against two existing private cached manifests. Existing SparkEventLogAdapter supplied exclusive directory ownership with empty SparkSecrets and an HTTP MockTransport that rejects any request; the shared SparkInspectionAdapter supplied Stage metrics, selected-Stage distribution and query ref rereading. No authentication configuration or credentials were read and no upstream request occurred.

| Application / attempt | JSONL bytes | Stage attempts | Selected Stage / attempt | Stage duration ms | TaskEnd / Success | Duration P50 / P95 ms | Stage seconds | Distribution seconds |
| --- | ---: | ---: | --- | ---: | --- | --- | ---: | ---: |
| application_1783000588461_681757 / 1 | 4008504 | 7 | 0 / 0 | 84171 | 200 / 200 | 640 / 5565 | 0.076 | 0.065 |
| application_1783000588461_687089 / 2 | 6205392 | 2 | 0 / 0 | 89351 | 1500 / 1500 | 2186 / 3714 | 0.116 | 0.101 |

Independent raw JSONL traversal checked SHA-256, selected-group TaskEnd and Success counts, timestamp-derived duration samples and nearest-rank P50/P95 against returned values. Top TaskEnd refs were reread through query using the same digest and matched direct task ID/ref. Evidence bytes and mtime remained unchanged. Ownership was closed after each run; HTTP requests: zero.

Process peak was 45.44 MiB on macOS, including interpreter/imports and the independent verification pass; it is not incremental parser memory. These are approximately 4 MB and 6 MB successful snapshots, not a 100 MB benchmark, live-backend/authentication test, deployed-host test or proof of a production root cause. Only safe counts/times were recorded; real event bodies were not added to the repository.

## Final integrated results

All commands below exited 0 against implementation HEAD `4c430b7` on branch `codex/spark-job-failure-diagnosis`.

| Command | Actual result |
| --- | --- |
| `uv sync --locked` | Resolved 57 packages with the committed lock; no dependency change. |
| `uv sync --locked --no-editable --reinstall-package hive-cli-mcp-stdio` | Rebuilt and installed the current project as a regular package. |
| `UV_NO_EDITABLE=1 uv run --locked pytest` | 1964 passed, 6 skipped, 6 deselected in 29.20 seconds; 1976 collected, 1970 selected. |
| `UV_NO_EDITABLE=1 uv run --locked ruff check .` | All checks passed. |
| `UV_NO_EDITABLE=1 uv run --locked pyright` | 0 errors, 0 warnings, 0 informations. |
| `uv build` | Built `dist/hive_cli_mcp_stdio-0.1.0.tar.gz` and `dist/hive_cli_mcp_stdio-0.1.0-py3-none-any.whl`. |
| `UV_NO_EDITABLE=1 uv run --locked mcp-stdio --help` | Console help succeeded and listed the four built-in plugins; no upstream access. |
| `openspec validate add-spark-performance-metrics --strict` | Change valid. |
| `openspec validate --changes --strict` | 17 passed, 0 failed. |
| `openspec validate --specs --strict` | 2 passed, 0 failed. |
| `git diff --check` | No whitespace errors. |

The regular-package installation is a local verification adjustment for the previously diagnosed macOS hidden editable `.pth`; subsequent commands retained locked execution with `UV_NO_EDITABLE=1`. No production code, project workflow, lock or configuration was changed for this adjustment. Package installation was completed sequentially before parallel independent checks.

The configured default test run excludes marked integration cases and skips six opt-in DolphinScheduler cases without required settings. No live backend integration was executed. Pyright also printed an updater notice, distinct from diagnostics. OpenSpec emitted existing unrelated archive-order INFO notices and a main-spec length notice; all strict validations passed, and those unrelated artifacts were preserved.

Task 3.2 additionally recorded the controller's fresh 60-test Skill/configuration check and three synthetic scenarios with 48 actual in-process MCP calls through production composition. Snapshot digests, returned values, population counts and physical event refs were checked. This verifies the reference workflow, not an improvement in Agent behavior or a production root cause; stdio wire behavior is covered separately by the contract suite.

## Whole-change review

An independent read-only review covered `82ca6a7..4c430b7` (14 commits), the active OpenSpec artifacts, implementation and runtime integration, tests, Skill, READMEs, architecture documents and task evidence. The review found no Critical, Important or actionable Minor issues. It checked numerical/sampling/ranking/ref semantics, complete snapshot validation, cancellation and ownership, public output safety, architecture and engineering economy. The reviewer did not rerun the controller's final suite or mark tasks complete.

The economy assessment supports the approved scope: two offline fact tools, per-Stage counters/totals/refs, six compact numeric arrays for a selected Stage, and at most `limit` ranked Task projections. No DiagnosisState, persistent aggregate/index, new dependency or configuration was added. Exact percentile sorting uses one temporary list per metric; cancellation is checked before and after synchronous sorting, not during it. The available samples do not establish 100 MB capacity. All existing task 4.1 gates passed; no push, merge, archive or global-client deployment was performed.

## Configuration example correction

The existing file-mode loader requires an explicit secrets mapping even for credential-free reads. A local `load_config(..., environ={})` check of the proposed settings-only JSON rejected it with `CONFIG_ERROR: secrets must be an object`; adding `secrets: {}` was accepted. The active design's field table and YAML example were corrected to document this existing requirement. No configuration behavior, credential, network request or production code changed.
