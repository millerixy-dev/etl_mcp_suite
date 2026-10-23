# Task 1.1 evidence

The controller executed the documentation task inline because routing, references and installer/example checks share a single contract. tasks.md is the only acceptance checklist. No production module, installer, dependency, configuration or MCP contract changed.

## Baseline and RED

Before editing the Skill, copied its bytes to /tmp/spark-event-reference-baseline-skill.md and ran an independent offline retrieval/application evaluation using only that snapshot and actual inspection_models.py. The baseline correctly produced FetchFailed, SQL execution 42→JobStart→JobEnd and line 17 expanded-reread query examples, with explicit placeholder values and causal limits. It reported no Skill basis for TaskGettingResult meaning or original Shuffle Write Time units. This was a documentation retrieval gap, not a demonstrated incorrect diagnosis or behavioral regression. Full answer: /tmp/spark-event-reference-baseline-report.md.

Added two reference/example checks and extended the existing real two-client installer test to compare all copied files recursively, rather than only SKILL.md. Ran:

`UV_NO_EDITABLE=1 uv run --locked pytest tests/unit/test_agent_skills.py -k 'spark_skill_reference or spark_search_examples'`

Actual RED: 2 failed, 26 deselected in 0.14 seconds. The Skill had no references links; event-search.md did not exist. These failures preceded writing the reference resources and Skill routing.

## GREEN and verification

Added references/spark-events-2.4.7.md and references/event-search.md, a short Skill routing section, and both README links. The reference covers common lifecycle/SQL/storage events, Reason meanings, direct and nested identifiers, projected/omitted fields, original units, log recording and causal limitations. The guide contains five actual query_spark_events request examples, reference-only rg commands and a FetchFailed recovery evidence-selection example. Examples are documented placeholders, not live evidence or tool invocations.

| Command | Actual result |
| --- | --- |
| `UV_NO_EDITABLE=1 uv run --locked pytest tests/unit/test_agent_skills.py` | 28 passed in 2.24 seconds, including real recursive installation tests for both clients and all five request examples validated against QueryRequest. |
| `uv run --locked --no-sync python /Users/liji/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/spark-diagnosis` | Skill is valid. |
| `UV_NO_EDITABLE=1 uv run --locked ruff check tests/unit/test_agent_skills.py` | All checks passed. |
| `UV_NO_EDITABLE=1 uv run --locked pyright tests/unit/test_agent_skills.py` | 0 errors, 0 warnings, 0 informations; separate updater notice. |
| Three `rg -n -F --` commands from event-search.md, run in skills/spark-diagnosis | All exited 0 and located FetchFailed, Shuffle Write Time and SQL execution in the stated reference files. |
| `git diff --check` | No whitespace errors. |

Independent forward evaluation used the updated Skill and its linked resources plus the same query model. It retrieved the specific references for Driver remote Task-result acquisition and nanosecond Shuffle Write Time, and produced four valid query examples with placeholder and fixed-projection limitations. Full answer: /tmp/spark-event-reference-forward-report.md. Controller read both complete reports and validated all eight JSON examples against the actual QueryRequest; baseline=4 and forward=4 passed.

The evaluation was offline retrieval/static-query validation only: no actual MCP request, backend, private evidence, credentials, production root cause or measured Agent effectiveness improvement. Baseline reasoning was already correct where guidance existed. The new reference makes previously absent version-specific knowledge retrievable; it does not prove diagnosis accuracy for an application.

Independent whole-change review and final acceptance are recorded in verification-report.md before controller checkbox gating.
