# Whole-change verification

## Scope and review

Implementation branch: `codex/zeppelin-restart-setting-id`.
Verification date: 2026-10-12.

Implementation and fresh verification cover commit `a494174`. Independent
whole-change re-review approved this commit with no remaining Critical, Important
or Minor findings. The controlling agent ran the complete final checks below;
the reviewer inspected the repair diff and regression evidence independently.

The whole-change review identified restart result strings containing session or
query secrets, raw HTTP transport logging during normal FastMCP startup, and
error-identifier filtering gaps. Regression tests use synthetic sentinels,
MockTransport and fake WebSocket connections; no live backend was contacted during
that automated verification. A subsequent authorized live check is recorded below.
Repairs reject tainted public result fields, silence raw HTTP transport logs,
filter error identifiers with available session and per-call secrets, and cover
cookie rotation, partial ticket validation, timeout and cancellation. Legacy error
metadata and clean empty-role results are covered by compatibility regressions.

## Verification commands and results

All commands run from the repository root. Each command below exited with code 0.

| Command | Result |
| --- | --- |
| `uv sync --locked` | Resolved 57 packages; checked 51 packages |
| `chflags nohidden .venv/lib/python3.12/site-packages/_editable_impl_hive_cli_mcp_stdio.pth && PYTHONPATH=src uv run --locked pytest tests/unit tests/contract -q` | 1,455 passed in 13.83s |
| `uv run --locked ruff check .` | All checks passed |
| `uv run --locked pyright` | 0 errors, 0 warnings, 0 informations |
| `uv build` | Built source distribution and wheel |
| `chflags nohidden .venv/lib/python3.12/site-packages/_editable_impl_hive_cli_mcp_stdio.pth && uv run --locked mcp-stdio --help` | Console usage/options printed successfully |
| `openspec validate support-zeppelin-notebook-interpreter-restart --strict` | Valid |
| `openspec validate --changes --strict` | 13 passed, 0 failed |
| `openspec validate --specs --strict` | 2 passed, 0 failed |
| `PYTHONPATH=src MCP_STDIO_ZEPPELIN_INTEGRATION=0 MCP_STDIO_ZEPPELIN_RESTART_INTEGRATION=0 uv run --locked pytest tests/integration/test_opt_in.py -o addopts='' -q` | 22 passed in 0.14s |
| `PYTHONPATH=src MCP_STDIO_ZEPPELIN_INTEGRATION=0 MCP_STDIO_ZEPPELIN_RESTART_INTEGRATION=0 uv run --locked pytest tests/integration/test_zeppelin_server.py -o addopts='' -m integration -q` | 3 skipped in 0.13s; no live discovery/restart claim |
| `git diff --check` | Passed |

## Local environment and remaining deployment limits

The local editable-install `.pth` repeatedly acquires the macOS hidden flag.
Earlier unmodified test commands failed with `ModuleNotFoundError: mcp_stdio`,
including child processes after clearing the flag. The test-only `PYTHONPATH=src`
prefix keeps this source checkout visible throughout verification. No permanent
environment, production installation or MCP host registration was changed.
This does not establish source isolation: an existing editable MCP installation
may still load this checkout. Switching production to an isolated installation
is a separate deployment step, not part of this feature verification.
The console smoke test succeeded after clearing the flag without `PYTHONPATH`.

Pyright printed an available-version notice (1.1.411 to 1.1.414), not a type
diagnostic. OpenSpec strict validation passed, but reports archive-order
dependencies: predecessor Zeppelin capability changes must be consolidated before
archiving this MODIFIED delta. Main-spec validation also reports an informational
long-requirement suggestion. This change has not been archived.

The automated run above skipped the live suite. Running that suite requires the
documented independent opt-in controls and explicit authorization for a dedicated
disposable target. Mock success alone does not establish live deployment
compatibility or permission behavior.

## Authorized live recovery check — 2026-10-12

After automated verification, the user explicitly requested recovery of notebook
`2N48NMDU7`, paragraph `paragraph_1791783836298_324182113`, and selected the
`spark_qysjrh` setting when discovery returned two eligible bindings. This was a
manual MCP recovery check on the user-selected target, not the opt-in pytest suite.

| MCP operation | Observed result |
| --- | --- |
| `get_paragraph_result` | `ERROR`: `SparkContext was shut down` |
| `get_interpreter_bindings` | `spark` and `spark_qysjrh` both selected and locally restart-allowed |
| `restart_interpreter(setting_id="spark_qysjrh", notebook_id="2N48NMDU7")` | One call returned `name="spark_qysjrh"`, `group="spark"`, `status="READY"` |
| `run_paragraph` on the original paragraph | Submitted once; returned `PENDING` |
| `get_paragraph_status` polling | Progressed through `RUNNING` to `FINISHED` |
| `get_paragraph_result` after completion | Table with 11 data rows, `error=null`, `truncated=false` |

This confirms binding discovery, notebook-context restart and successful execution
recovery for this target using the registered MCP tools. No global restart fallback
or repeat restart was performed. The check does not establish the account's admin
role, behavior of other settings, or completion of local production isolation.
Credentials, connection details, raw stack traces and query data are omitted.
