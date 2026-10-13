# Task 4.1 verification micro-plan

OpenSpec tasks.md is the authoritative checklist. This task changes no behavior; it verifies the integrated deliverable and records evidence in task-4.1-report.md before the controller gates completion.

1. Run `uv sync --locked`; expect the committed dependency lock to resolve without dependency edits. Local macOS repeatedly hides the editable .pth, including during child-process startup. If flag clearing does not persist, use `uv sync --locked --no-editable` and `UV_NO_EDITABLE=1` for verification commands, installing the same current project without a .pth. Do not change project source/config workflows for this local environment issue.
2. Run `uv run --locked pytest`; expect the complete configured unit/contract suite to pass and opt-in integration to remain excluded. Run `uv run --locked ruff check .` and `uv run --locked pyright`; expect zero lint/type errors.
3. Run `uv build` and `uv run --locked mcp-stdio --help`; expect wheel/sdist generation and the existing console entry point to succeed without upstream access.
4. Run `openspec validate add-spark-event-log-inspection --strict`, `openspec validate --changes --strict` and `openspec validate --specs --strict`; expect no failed validations, with unrelated existing archive-order informational notices recorded honestly.
5. Perform a read-only whole-change code review of `/tmp/spark-inspection-whole-change.diff` (baseline cd8abb0, before this capability implementation). Fix substantive findings through targeted RED/GREEN verification and review before gating; preserve other active change artifacts.
6. Record the already performed local success-sample benchmark: two selected private manifests, exclusive existing directory ownership, inspect/query digest+count checks, no network calls. Record actual sample sizes/times/process peak; do not claim 100 MB or live-backend validation.
7. Check `git diff --check` and final ownership/status. Commit only this capability's verification evidence and task gate; do not push, merge, archive, or stage the user's other active change.
