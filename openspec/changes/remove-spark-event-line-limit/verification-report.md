# Verification — 2026-10-14

## Outcome

Removed the independent 8 MiB input/output record cap from acquisition and the shared offline reader. max_bytes still independently bounds ZIP transport, aggregate expanded source and aggregate sanitized output; each record read uses remaining aggregate budget + 1 and checks overflow before parsing. No tool/config/result schema changes.

## TDD and review

- RED: nine new synthetic cases initially lived in test_event_budgets.py. `UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/plugins/spark/test_event_budgets.py -q` returned **2 failed, 7 passed**: large acquisition rejected by files.py and large offline scan rejected by inspection_reader.py.
- Initial GREEN run exposed slow existing redaction of a contiguous alphabetic string (see limitation below); stopped only the test process. Changed the synthetic large payload to whitespace-separated `node ` without changing its >8 MiB size purpose. Focused result **9 passed in 1.85s**.
- Type checking rejected importing private test_files._process across test modules. Moved acquisition cases into test_files.py and offline cases into test_inspection.py, preserving the same nine cases and using existing local helpers. Corrected one test line-length issue. Production change was unaffected.
- `UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/plugins/spark tests/contract/test_spark_stdio.py -q`: **462 passed in 21.00s**, before the test-only move.
- Independent read-only review of final code/tests: no blocking findings. Corrected one plan-only interface name. See review-report.md.

## Final commands and results

| Command | Result |
| --- | --- |
| `UV_NO_EDITABLE=1 uv run --locked pytest -q` | **1975 passed, 6 skipped, 6 deselected in 32.29s** after the final test move |
| `uv run --locked --no-editable ruff check .` | All checks passed |
| `uv run --locked --no-editable pyright` | 0 errors, 0 warnings, 0 informations |
| `uv build` | Source distribution and wheel built successfully |
| `uv run --locked --no-editable mcp-stdio --help` | Exit 0, console entry point listed built-in plugins |
| `openspec validate --changes --strict` | 18 passed, 0 failed |
| `openspec validate --specs --strict` | 3 passed, 0 failed |
| `git diff --check` | Passed |

OpenSpec emits existing informational notices about other unarchived capabilities and long requirements; no validation failures. No runtime dependency or package configuration changed. No live backend acquisition was run in this change; integration tests remain opt-in and were deselected.

## Known limitation and deployment

Large JSON parsing/redaction may use substantially more memory than serialized bytes. Existing `_USERINFO` regex processing of long uninterrupted alphabetic strings also has superlinear cost: bounded synthetic substitution experiments at 2000/4000/8000 characters took approximately 0.0127/0.0503/0.2016 seconds. This predates the byte-cap change, is not fixed here, and means large-event acceptance does not guarantee a processing latency bound for every event shape. Final size regressions use separated text to isolate record budgeting. No real events or credentials were used in tests or reports.

Restart the existing spark_dev child process to load changed code before retrying application_1783000588461_698181 attempt 1. The original ZIP remains available; this change does not claim a newly downloaded or sanitized production snapshot.

Changes are left in the working tree. Unrelated pre-existing executor-log and download-spec edits are preserved. The original download capability's resource sentence/design was intentionally synchronized to the approved aggregate-only policy; its other pending edits were retained.


## Commit preparation revalidation — 2026-10-14

The previously uncommitted fix is being committed separately from the pending executor-log proposal. No production behavior changed during commit preparation.

- `uv sync --locked`: passed.
- `PYTHONPATH=src uv run --locked pytest -q tests/unit/plugins/spark/test_files.py tests/unit/plugins/spark/test_inspection.py`: **74 passed in 15.91s**.
- `PYTHONPATH=src uv run --locked pytest -q`: **1975 passed, 6 skipped, 6 deselected in 31.56s**; live integration remained deselected.
- `uv run --locked ruff check .`: passed.
- `uv run --locked pyright`: 0 errors, 0 warnings, 0 informations.
- `uv build`: sdist and wheel built successfully.
- `uv run --locked mcp-stdio --help`: failed in the local editable environment with `ModuleNotFoundError: mcp_stdio.__main__`. Import inspection found only a site-packages namespace package despite the source entry point existing. No application source was changed to mask this environment issue.
- `uv run --locked --no-editable mcp-stdio --help`: passed after installing the non-editable package, consistent with the original verification workflow above.
- Strict OpenSpec validation: 18 changes and 3 main specs passed; existing informational notices remain.
- `git diff --check`: passed.

Executor/Driver log tool implementation remains pending; its planning documents are a separate commit, not a delivered feature. Live Driver log acquisition was not repeated during commit preparation.
