# Final verification evidence

Documentation-only change extend-spark-diagnosis-event-reference, implementation baseline HEAD 00a8929. Exact command/results below were freshly executed by the controller on the updated Skill, references, READMEs and tests; no runtime source changed. task-1.1-report.md records RED/GREEN and independent retrieval evidence. tasks.md is the only acceptance checklist.

| Command | Actual result |
| --- | --- |
| `UV_NO_EDITABLE=1 uv run --locked pytest` | 1966 passed, 6 skipped, 6 deselected in 29.22 seconds; 1978 collected / 1972 selected. |
| `UV_NO_EDITABLE=1 uv run --locked ruff check .` | All checks passed. |
| `UV_NO_EDITABLE=1 uv run --locked pyright` | 0 errors, 0 warnings, 0 informations. |
| `uv build` | Successfully built dist/hive_cli_mcp_stdio-0.1.0.tar.gz and dist/hive_cli_mcp_stdio-0.1.0-py3-none-any.whl. |
| `UV_NO_EDITABLE=1 uv run --locked mcp-stdio --help` | Console help exited 0 and listed four built-in plugins, with no upstream access. |
| `openspec validate extend-spark-diagnosis-event-reference --strict` | Valid, exit 0; skip_specs documents the absence of runtime/spec-level contract changes. |
| `openspec validate --changes --strict` | 17 passed, 0 failed. |
| `openspec validate --specs --strict` | 3 passed, 0 failed. |
| `git diff --check` / `git diff --cached --check` | Both exited 0 without whitespace errors. |

The installed project was already a regular package. UV_NO_EDITABLE=1 prevents the known local hidden-editable-.pth issue without changing project workflows or adding PYTHONPATH. Locked execution was preserved. Pyright emitted a separate updater notice; OpenSpec emitted existing archive-order/requirement-length INFO notices. None was a failed check.

Default configured pytest excludes marked integration cases and skipped six opt-in DolphinScheduler cases. No live cluster integration, authentication, new event-log acquisition or private-log search was executed. Independent retrieval evaluations used document/schema files only; neither is a real application diagnosis or a controlled Agent effectiveness study. All five guide examples and eight evaluation examples passed the real QueryRequest validator. Existing recursive installer behavior was tested in temporary projects; no installed user Skill or MCP settings were overwritten.

## Independent review

Independent read-only review examined /tmp/spark-event-reference-review.diff relative to HEAD 00a8929, authoritative proposal/design/tasks and task plan, actual query schema/direct-ID extraction/projections and installer behavior, and cited Apache Spark 2.4.7 sources. Verdict: spec compliance passed, documentation quality approved, no actionable Critical/Important/Minor issues. Reviewer did not edit the repository or repeat test suites. Full review report: /tmp/spark-event-reference-final-review.md.

Controller read the review and independently checked the baseline/forward answers and all their JSON requests. All existing task gates passed. Only canonical Skill documentation, two references, READMEs, resource/example tests and this change's documentation are included; unrelated download/executor work remains untouched. No global installation, push, merge or archive was performed.
