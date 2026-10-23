# Container log Skill micro-plan

Use writing-plans and executing-plans for this single coupled documentation task; writing-skills baseline/forward evaluations use independent agents. tasks.md is the only completion checklist.

Goal: incorporate existing container-log acquisition into evidence selection without adding runtime behavior.
Architecture: short SKILL.md routing and one optional container-logs reference. Python >=3.10, uv; no new dependency, secret or configuration.

## Task 1.1

Files: skills/spark-diagnosis/SKILL.md, references/event-search.md, new references/container-logs.md, README.md, README.zh-CN.md, tests/unit/test_agent_skills.py.
Consumes: existing SparkExecutorLogRequest and SparkExecutorLogFetchResult contracts. Produces: instructions and portable examples only.

RED: an independent agent reads the old Skill and handles five synthetic scenarios: unknown Driver failure, recovered FetchFailed, incomplete/mismatched evidence, download errors, and no local reader. Record actual omissions. Add a real model validation test for all JSON request/result examples in the new guide, plus its reference in the existing portable-links check. Core test:
```python
blocks = re.findall(r"```json\n(.*?)\n```", guide, flags=re.DOTALL)
for block in blocks:
    value = json.loads(block)
    if "local_path" in value:
        SparkExecutorLogFetchResult.model_validate(value)
    else:
        SparkExecutorLogRequest.model_validate(value)
```
Run `PYTHONPATH=src uv run --locked pytest -q tests/unit/test_agent_skills.py -k 'spark_skill_reference_links or container_log'`; expect missing reference/file failures, not model import failures.

GREEN: write the guide per design with the exact existing input table, one Driver request, one numeric executor request and one result. Change the main discovery list to include fetch_spark_executor_log; route to the reference for external evidence; distinguish saved container-text searches from event JSONL queries in event-search.md. Add one usage paragraph/link in each README. No scripts or production code.

Verify `PYTHONPATH=src uv run --locked pytest -q tests/unit/test_agent_skills.py` and `uv run --locked python /Users/liji/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/spark-diagnosis`. Forward-evaluate same five scenarios with an independent fresh-context agent; compare observable actions, not word matching. Review failures and refine only demonstrated ambiguities.

## Task 2.1

Document-only gate. Run `PYTHONPATH=src uv run --locked pytest -q`, `uv run --locked ruff check .`, `uv run --locked pyright`, `uv build`, `uv run --locked --no-editable mcp-stdio --help`, `openspec validate --changes --strict`, `openspec validate --specs --strict`, `git diff --check`. Expected pass; report integration deselections honestly. Record results in verification.md. Preserve pre-existing redaction fix and deployment edits; no automatic installation or publication.

Self-review: five scenarios cover routing, evidence access, identity/hash, tail bounds, missing capability, error handling and recovery. Existing installer tests verify recursively copied references. No public MCP changes require a new capability delta.
