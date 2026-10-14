# Task 3.2 Skill and documentation implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for this single tightly coupled OpenSpec task. This micro-plan expands task 3.2; tasks.md remains the sole completion checklist.

**Goal:** Extend the existing portable Spark diagnosis reference with slow-job metric selection and synchronized usage/architecture documentation.

**Architecture:** Existing FastMCP tools call SparkMetricsService through SparkMetricsGateway; the same SparkInspectionAdapter owns inspection and metrics workers. No runtime or deployment changes.

**Tech Stack:** Existing Python 3.10+ package, uv locked execution, pytest, Markdown Skill.

## Global constraints

Baseline: `899efc8`. Owned files: skills/spark-diagnosis/SKILL.md, README.md, README.zh-CN.md, docs/architecture/runtime-flow.md, docs/architecture/modules.md, tests/unit/test_agent_skills.py and this task's plan/report. Preserve failure diagnosis, client-neutral tool discovery, existing installation, strict schemas and snapshot pinning. No new state, query budget, dependencies, network, credentials or OpenSpec checkbox changes.

## Single task procedure

1. Run fresh-context baseline reference retrieval against the unedited Skill and actual tools.py/metrics_models.py. Record genuine absent guidance separately from competent independent reasoning. This is a reference extension, not a behavior-shaping intervention: no causal efficacy claim from control competence or keyword tests; five-repetition wording tests apply only if behavior shaping is claimed.
2. Extend CANONICAL_SKILLS with both metric names and add a performance discovery test:

```python
def test_spark_skill_discovers_successful_slow_applications() -> None:
    frontmatter, body = load_skill(PROJECT_ROOT / "skills/spark-diagnosis/SKILL.md")
    assert "performance" in str(frontmatter["description"])
    assert "long runtime" in str(frontmatter["description"])
    assert "SparkListenerApplicationStart" in body
    assert "SparkListenerApplicationEnd" in body
    assert "nearest-rank" in body
    assert "missing_count" in body
    assert "tasks_omitted" in body
```

Run `UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/test_agent_skills.py`; expect missing metric references/discovery to fail before Skill edits. Keep uv reinstalls sequential with parent's verification.
3. Add one concise slow-job branch: application timestamps; same manifest/attempt/hash; Stage ranking and explicit attempt; full success-sample distributions independent of ranking; correlated same-task comparisons; reread refs; retry/executor counterevidence; missing counts, omissions, nearest-rank, no logical dedup, no unsupported root cause or application time sum. Keep old failure branch intact.
4. Add both new tools, named results, exact inputs, fixed ordering/unit list and limitations to both READMEs. Reflect actual metrics service/port/adapter composition and worker ownership in both architecture views.
5. Repeat reference retrieval with updated Skill in a fresh context. Read every probe manually; report discovery/selection competence and any gaps without attributing general behavioral improvement.
6. Actual MCP manual procedure: create private synthetic manifests for A (four successes 100/100/100/900 seconds, Shuffle 100/100/100/900 million bytes), B (three successes 100/100/900 seconds, same 100 million bytes, waits10/10/700 seconds), C (failed Stage0 and successful Stage1, independent duration/Shuffle missing cells). Use consistent app timestamps spanning2880000ms; stages/tasks inside that span. Via actual StdioMcpServer FastMCP dispatch list schema, inspect, query ApplicationStart/End, pin hash, Stage metrics, explicit distribution limit20 and limit1 alternate ordering, source-ref rereads, retry/executor queries. Record all inputs/results/hashes/lines and named models. Assert distributions remain unchanged under ordering/limit changes. A yields skew candidate; B wait candidate without network/OOM proof; C separates recovery and missing coverage. Explain uncovered app time, not a fabricated full48min attribution. Close runtime and deny network.
7. Run fresh Skill tests, nearest documentation/architecture checks and strict change/spec validation. Record exact command/results; stdio protocol and live backend are distinct and not exercised by this manual harness. Self-review owned diff, commit only owned files, leave checkboxes to parent.
