# Spark diagnosis Skill implementation plan

> Execution: this delegated task follows superpowers:executing-plans inline. OpenSpec tasks.md remains the only completion checklist.

**Goal:** Deliver portable snapshot-pinned diagnosis guidance and distribution, with actual five-case evidence exercises.

**Architecture:** The Skill consumes inspect/query contracts; diagnosis stays in agent reasoning. Installation copies canonical files without adding a Spark server to managed host configuration.

**Tech Stack:** Markdown, existing shell installers, pytest via locked uv; existing Spark inspection APIs for synthetic evidence.

## Authoritative scope

OpenSpec task 3.2, proposal.md, design.md and specs/spark-event-log-inspection/spec.md in this change. No production Python or task checkbox changes.

## Execution micro-plan

1. Extend CANONICAL_SKILLS with spark-diagnosis and its three tool names; add REQUIRED_GUIDANCE entry. Run `uv run --locked pytest tests/unit/test_agent_skills.py` and observe missing canonical file/install failure before implementation.
2. Create skills/spark-diagnosis/SKILL.md with frontmatter, capability discovery, explicit manifest/attempt/hash pinning, own-field traversal, full-match counts, bounded critical-text expansion, recovery checks, conservative conclusions and untrusted-data boundary. Add its name to managed_skills and installation message only.
3. Update README.md, README.zh-CN.md and docs/architecture/{runtime-flow,modules}.md for the three-tool union, query parameters/results, local-only reads and actual module ownership; preserve acquisition TLS/authentication documentation.
4. Run the distribution suite again. Exercise terminal exception, successful retry, unknown executor-loss cause, incomplete log and all-success synthetic private snapshots through actual verified tools. Record query inputs, hashes, lines, distributions and reasoning in task-3.2-report.md; never implement a root-cause classifier.
5. Run fresh distribution tests, lint and strict change validation, review only owned diff, commit only owned deliverables. Parent gates tasks.md.

## Five-case pre-implementation oracle

| Synthetic evidence | Required conclusion | Counterevidence / missing proof |
| --- | --- | --- |
| Explicit JobFailed + task exception, no retry | supported, scoped job failure | Query all job endings and relevant stage attempts; no recovery |
| Initial failed task/stage + successful stage retry + JobSucceeded | no terminal failure observed; report recovery | Successful retry and JobEnd refute terminal-cause claim |
| FetchFailed + ExecutorRemoved reason unknown | inconclusive for OOM | No driver/executor/YARN exit evidence |
| Valid log without ending | inconclusive for terminal state | Missing JobEnd/ApplicationEnd; UNKNOWN reason is not success |
| All observed JobSucceeded | no_observed_failure scoped to observed jobs | End presence does not prove YARN/SQL success |
