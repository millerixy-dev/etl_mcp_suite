# Verification — 2026-10-15

## Scope and review

Updated canonical spark-diagnosis Skill, a new container-logs reference, event-search cross-links, both READMEs and tests/unit/test_agent_skills.py. No production behavior, MCP configuration, credentials or installed Skill copies changed. Existing redaction fix and docs/examples/spark-executor-logs.yaml edits were preserved.

The implementation uses OpenSpec apply with writing-plans/executing-plans for the coupled documentation task, and independent agents for writing-skills baseline, forward evaluation and contract review. Static review against executor_logs.py, executor_log_models.py, tools.py and cache.py found no actionable issue. Final wording distinguishes event-only inspect requirements from direct container downloads and distinguishes event refs from container-file citations.

## RED / GREEN

Before writing the guide:

`PYTHONPATH=src uv run --locked pytest -q tests/unit/test_agent_skills.py -k 'spark_skill_reference_links or container_log'`

Result: 2 failed, 27 deselected. Failures were the missing container-logs reference/link and absent example file; models imported correctly. These checks cover reference availability and examples, not agent reasoning.

After authoring, the full Skill test file passed: 29 passed. New examples validate through actual SparkExecutorLogRequest and SparkExecutorLogFetchResult models; result/request identities and stream/range agree. Existing installer tests recursively compare every copied resource and preserve unrelated files. No wording-only test was added to claim behavioral correctness.

## Independent offline behavioral evaluation

Both evaluations used fresh context, current Skill and its references, the actual container tool signature, and the same five synthetic scenarios. They were prohibited from reading implementation/OpenSpec, accessing online MCP/network or editing files. Given example paths were not claimed to have been opened. This is a single qualitative pass per scenario, not a statistical measure of model accuracy or a live integration test.

| Scenario | Baseline before edit | Forward evaluation after edit |
|---|---|---|
| A: Job success, 29 ms SQL without JobStart, Driver stderr only exit 1 | Expanded stderr to 1 MiB first; then stdout. Correctly kept root cause inconclusive | First requested Driver stdout 65536; conditional bounded expansion, preserved unknown cause |
| B: Task executor 9 / Shuffle provider 4, later recovery | Correctly selected provider 4, distinguished identities, retained recovery | Same correct distinction, additionally explained Task executor filter cannot stand in for provider lookup |
| C: short saved file, coverage=tail, event digest mismatch | Correctly kept incomplete coverage and independent source | Same, with conditional other-stream/range selection and explicit no synchronized-freeze claim |
| D: NOT_FOUND vs AUTHENTICATION_FAILED | Did not invent log refresh parameter or bypass auth; omitted the explicit stale-cache refresh route | Did not refresh without evidence of staleness; described one explicit event refresh and new inspect only if justified; stopped auth path |
| E: user wants only stdout, download succeeds but no local reader | Correctly reported download-only evidence and stopped | Reused returned result, no repeated download/other-stream expansion, no claim to read or independently hash |

Baseline did not demonstrate fabricated diagnoses or universal workflow failure. Its observed differences were acquisition order and missing stale-cache guidance. The documentation makes the existing workflow discoverable and standardizes those choices; no broader performance improvement is claimed.

Representative observed choices:
- Baseline A: “为查找 driver 中更早的异常” selected stderr with tail_bytes=1048576 before stdout.
- Forward A: “下一次取证优先补 stdout” with tail_bytes=65536; “不会先把 stderr 扩大到最大”.
- Forward E: “当前没有该文件的本地读取能力，因此尚未读取或核验正文，不能判断其中是否有异常”.

## Automated verification

| Command | Result |
|---|---|
| `PYTHONPATH=src uv run --locked pytest -q tests/unit/test_agent_skills.py` | 29 passed; repeated after final wording edits |
| `uv run --locked python /Users/liji/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/spark-diagnosis` | Skill is valid |
| `PYTHONPATH=src uv run --locked pytest -q` | 2087 passed, 6 skipped, 7 deselected, 34.73 s |
| `uv run --locked ruff check .` | All checks passed |
| `uv run --locked pyright` | 0 errors, 0 warnings |
| `uv build` | sdist and wheel built |
| `uv run --locked --no-editable mcp-stdio --help` | Exit 0 |
| `openspec validate --changes --strict` | 20 passed, 0 failed |
| `openspec validate --specs --strict` | 3 passed, 0 failed |
| `git diff --check` | Exit 0 |

Integration tests remained deselected; no real cluster calls were needed for this documentation change. Existing informational OpenSpec notes about other changes' archive prerequisites and long requirements remain unrelated. Installation was exercised only in disposable test directories; canonical files are ready for the existing project-local installer workflow.
