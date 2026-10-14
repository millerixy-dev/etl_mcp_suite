# Task 1.1 micro-plan

Execution: inline executing-plans; Skill routing, two references and installer/example tests share one documentation contract and run serially. Independent read-only baseline/forward evaluation and final review remain separate. tasks.md is the sole acceptance checklist.

1. Before editing the Skill, save its existing text at /tmp/spark-event-reference-baseline-skill.md. Independent agent answers offline retrieval/application questions about TaskGettingResult, Shuffle Write units, FetchFailed recovery, SQL linking and details limits using only supplied Skill/schema. Record actual missing guidance and behavior, without assuming the agent will reason incorrectly.
2. RED: import re and QueryRequest in tests/unit/test_agent_skills.py; add a test resolving relative reference links discovered in the Skill, requiring both proposed files. Add a test parsing JSON code blocks from event-search.md and passing each to QueryRequest.model_validate. Extend the existing two-client installer test to compare every file under each canonical Skill, including reference resources. Smallest command: `UV_NO_EDITABLE=1 uv run --locked pytest tests/unit/test_agent_skills.py -k 'spark_skill_reference or spark_search_examples'`; expect two failures from missing resources/links.

   Core test expressions:

   ```python
   reference_targets = re.findall(r"\]\((references/[^)]+)\)", body)
   assert {"references/spark-events-2.4.7.md", "references/event-search.md"} <= set(reference_targets)
   for target in reference_targets:
       resolved = (skill_root / target).resolve()
       assert resolved.is_relative_to(skill_root.resolve())
       assert resolved.is_file()
   blocks = re.findall(r"```json\n(.*?)\n```", guide, flags=re.DOTALL)
   assert len(blocks) >= 3
   for block in blocks:
       QueryRequest.model_validate(json.loads(block))
   for source in (PROJECT_ROOT / "skills" / skill_name).rglob("*"):
       if source.is_file():
           assert installed_root.joinpath(source.relative_to(source_root)).read_bytes() == source.read_bytes()
   ```

3. GREEN: add references/spark-events-2.4.7.md with version/source notes, grouped lifecycle/SQL/storage event tables, Task End Reason meanings and raw metric units; distinguish Event names from Reason values, source fields from MCP projections, direct IDs from nested arrays, null fields and log configuration. Add references/event-search.md with truthful existing-MCP JSON queries and reference-only rg commands, pagination/reread rules and one FetchFailed recovery example. Add one short Skill routing section and README links. No runtime or installer edits.
4. Verify `UV_NO_EDITABLE=1 uv run --locked pytest tests/unit/test_agent_skills.py`; expect all existing portability/installation checks plus new resource/schema checks to pass. Run `uv run --locked --no-sync python /Users/liji/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/spark-diagnosis`. Independent evaluator repeats the same offline scenarios with the Skill and linked files. Inspect actual answer and QueryRequest validity; record source availability vs correct reasoning separately.
5. Self-review for guessed fields, fake tool parameters, incorrect full names, units, unbounded output, duplicated workflow or incidental permissions. Record evidence in task-1.1-report.md. Controller freshly verifies tests; task checkbox gates on docs, tests, evaluation and review. Final broader review/checks occur in task 2.1.
