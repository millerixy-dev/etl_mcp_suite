# Task 3.2 evidence report

Authoritative task: [tasks.md](tasks.md), 3.2. This report records evidence and does not gate its checkbox.

## RED / GREEN and authoring sequence

`uv run --locked pytest tests/unit/test_agent_skills.py` after registering spark-diagnosis in CANONICAL_SKILLS/REQUIRED_GUIDANCE: **5 failed, 20 passed**, missing canonical file and missing installed files in both clients (normal/force paths). After creating Skill and registering only the copied skill name: **25 passed**. Existing managed MCP server sets remain unchanged.

An initial uncommitted Skill draft was written before independent pressure testing. That ordering was incorrect for writing-skills. It was removed; a fresh independent no-guidance baseline ran while SKILL.md was absent, then the Skill was newly authored from the approved contract and observed omissions. No claim is made that the first draft followed behavioral RED.

First no-guidance control correctly refused OOM, but suggested shortened `event_types=["TaskEnd"]`, omitted explicit snapshot inputs, and did not check recovery. Fresh baseline also correctly rejected the first-page-success inference, but gave `limit=30` and expanded text without explicit `limit=1`, manifest, attempt or hash. Verbatim baseline query fragments:

```json
{"event_types":["SparkListenerTaskEnd"],"stage_id":3,"after_line":11,"limit":30}
{"event_types":["SparkListenerExecutorRemoved"],"lines":[70],"max_detail_chars":20000}
```

The baseline prompt did not include numeric ranges, so limit=30 is a discoverability omission, not a claimed failure to obey supplied range instructions. The missing required query inputs and invalid expanded-read combination expose the need for the Skill's concrete pinned single-line pattern. No baseline incorrectly asserting OOM or no failure was observed; that must not be reported as a demonstrated correction.

Independent guided GREEN evaluation read only the newly authored Skill and the same pressure scenario. It rejected the page-success inference, scoped the observed failure, kept executor cause and recovery inconclusive, supplied all manifest/attempt/copied-hash inputs, used exact SparkListenerTaskEnd + FetchFailed selection with limit=1, expanded lines=[70] with limit=1/max_detail_chars=32768, and requested stage submitted/completed records to check recovery. It explicitly said these were proposed calls, not executed results. This corrects the concrete query-shape omissions; it does not demonstrate a change from falsely asserting OOM because neither control did so.

## Five actual MCP exercises

Executed `PYTHONPATH=.:src uv run --locked python /tmp/spark-five-cases.py` using `StdioMcpServer._fastmcp.call_tool`, the actual Spark runtime, actual inspection service/adapter and verified private temporary JSONL/manifest fixtures. Tool listing was the exact fetch/inspect/query union. No live cluster, credentials or HTTP calls; existing fixtures supplied only synthetic records. Temporary evidence was deleted after exercise. This is actual in-process MCP dispatch, not a real stdio transport or deployed host test.

Harness setup initially lacked Python import paths, then macOS temporary-path aliases caused a manifest absolute-path mismatch. The final harness uses `PYTHONPATH=.:src` and resolves the temporary root before creating matching manifests. No production change was required. The final run below completed every query and closed each runtime.

Input oracle was defined before implementation in task-3.2-plan.md. A temporary harness collects tool results only; the following conclusions are manual reasoning, not a backend or test root-cause classifier.

For each case below, every query expands `base` + `expected_sha256` + the shown selection exactly. Returned line numbers refer to that case's full SHA-256; JSONL physical lines 1–2 are LogStart/ApplicationStart. Each record ref returned the same snapshot digest. Full-match counts are recorded even when pages return one entry. Unknown IDs remain null.

### terminal_exception

Snapshot SHA-256: `3925d15d42618ba505588e805ec088ee6e5fc716d97f4fc7d3e3c1a7297b87e9`.

Actual inspect/base input:

```json
{"manifest_path": "/private/var/folders/p_/n6lzpss53zv47fjwl9vbhk1m0000gp/T/spark-diagnosis-v4iu9sl3/terminal_exception/l3/application_1_42/all/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/manifest.json", "attempt_id": null}
```

Verified overview:

```json
{"event_count": 7, "signals": {"job_failed_events": 1, "stage_failure_events": 1, "task_non_success_events": 1, "executor_removed_events": 0}, "task_end_count": 1, "task_end_reasons": [{"reason": "ExceptionFailure", "count": 1}], "coverage": {"application_start_seen": true, "application_end_seen": true}, "evidence_omitted": 0, "evidence_refs": [{"sha256": "3925d15d42618ba505588e805ec088ee6e5fc716d97f4fc7d3e3c1a7297b87e9", "line": 6}, {"sha256": "3925d15d42618ba505588e805ec088ee6e5fc716d97f4fc7d3e3c1a7297b87e9", "line": 5}, {"sha256": "3925d15d42618ba505588e805ec088ee6e5fc716d97f4fc7d3e3c1a7297b87e9", "line": 4}]}
```

| Actual query selection (with base + copied hash) | matched / returned | TaskEnd reasons over full matches | Returned lines; next cursor |
| --- | --- | --- | --- |
| `{"job_id":7}` | 2 / 2 | `[]` | [3, 6]; None |
| `{"execution_id":5}` | 1 / 1 | `[]` | [3]; None |
| `{"stage_id":3,"event_types":["SparkListenerTaskEnd","SparkListenerStageCompleted"],"limit":1}` | 2 / 1 | `[{"reason":"ExceptionFailure","count":1}]` | [4]; 4 |
| `{"stage_id":3,"event_types":["SparkListenerTaskEnd","SparkListenerStageCompleted"],"limit":1,"after_line":4}` | 2 / 1 | `[{"reason":"ExceptionFailure","count":1}]` | [5]; None |
| `{"event_types":["SparkListenerJobEnd"]}` | 1 / 1 | `[]` | [6]; None |
| `{"stage_id":3,"task_end_reason":"ExceptionFailure"}` | 1 / 1 | `[{"reason":"ExceptionFailure","count":1}]` | [4]; None |
| `{"lines":[4],"limit":1,"max_detail_chars":32768}` | 1 / 1 | `[{"reason":"ExceptionFailure","count":1}]` | [4]; None |

**supported**, scoped to Job 7's failed stage 3: task line 4 contains java.lang.ArithmeticException: / by zero; stage line 5 gives the same failure and JobEnd line 6 reports JobFailed with an arithmetic exception. All related stage records and all observed JobEnd events were read; no later stage retry/success is observed. The critical task description is initially truncated and the pinned line-4 expansion returns the exception untruncated. The log cannot prove YARN terminal state or exclude absent upstream evidence.

### retry_recovery

Snapshot SHA-256: `0362ea05d68e7438fb03ce43d781015e4b18ac1e93cfa693b1686fa939970d6c`.

Actual inspect/base input:

```json
{"manifest_path": "/private/var/folders/p_/n6lzpss53zv47fjwl9vbhk1m0000gp/T/spark-diagnosis-v4iu9sl3/retry_recovery/l3/application_1_42/all/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/manifest.json", "attempt_id": null}
```

Verified overview:

```json
{"event_count": 9, "signals": {"job_failed_events": 0, "stage_failure_events": 1, "task_non_success_events": 1, "executor_removed_events": 0}, "task_end_count": 2, "task_end_reasons": [{"reason": "ExceptionFailure", "count": 1}, {"reason": "Success", "count": 1}], "coverage": {"application_start_seen": true, "application_end_seen": true}, "evidence_omitted": 0, "evidence_refs": [{"sha256": "0362ea05d68e7438fb03ce43d781015e4b18ac1e93cfa693b1686fa939970d6c", "line": 5}, {"sha256": "0362ea05d68e7438fb03ce43d781015e4b18ac1e93cfa693b1686fa939970d6c", "line": 4}]}
```

| Actual query selection (with base + copied hash) | matched / returned | TaskEnd reasons over full matches | Returned lines; next cursor |
| --- | --- | --- | --- |
| `{"job_id":7}` | 2 / 2 | `[]` | [3, 8]; None |
| `{"execution_id":5}` | 1 / 1 | `[]` | [3]; None |
| `{"stage_id":3,"event_types":["SparkListenerTaskEnd","SparkListenerStageCompleted"],"limit":1}` | 4 / 1 | `[{"reason":"ExceptionFailure","count":1},{"reason":"Success","count":1}]` | [4]; 4 |
| `{"stage_id":3,"event_types":["SparkListenerTaskEnd","SparkListenerStageCompleted"],"limit":1,"after_line":4}` | 4 / 1 | `[{"reason":"ExceptionFailure","count":1},{"reason":"Success","count":1}]` | [5]; 5 |
| `{"stage_id":3,"event_types":["SparkListenerTaskEnd","SparkListenerStageCompleted"],"limit":1,"after_line":5}` | 4 / 1 | `[{"reason":"ExceptionFailure","count":1},{"reason":"Success","count":1}]` | [6]; 6 |
| `{"stage_id":3,"event_types":["SparkListenerTaskEnd","SparkListenerStageCompleted"],"limit":1,"after_line":6}` | 4 / 1 | `[{"reason":"ExceptionFailure","count":1},{"reason":"Success","count":1}]` | [7]; None |
| `{"event_types":["SparkListenerJobEnd"]}` | 1 / 1 | `[]` | [8]; None |
| `{"stage_id":3,"stage_attempt_id":1}` | 2 / 2 | `[{"reason":"Success","count":1}]` | [6, 7]; None |

**no_observed_failure**, scoped to terminal failure of observed Job 7, with explicit recovered transient failure: initial ExceptionFailure task line 4 and failed stage-attempt 0 line 5 are facts, but Success task line 6, completed stage-attempt 1 line 7 and JobSucceeded line 8 refute the terminal-cause hypothesis. Stage-attempt-1 query matches both recovery records. This does not erase the earlier non-success signal and does not assert YARN/SQL success.

### executor_unknown

Snapshot SHA-256: `ed369567768e26b937b3f80e42a419c56ed918516b6594cb7e2def0b14f3dbd5`.

Actual inspect/base input:

```json
{"manifest_path": "/private/var/folders/p_/n6lzpss53zv47fjwl9vbhk1m0000gp/T/spark-diagnosis-v4iu9sl3/executor_unknown/l3/application_1_42/all/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/manifest.json", "attempt_id": null}
```

Verified overview:

```json
{"event_count": 8, "signals": {"job_failed_events": 1, "stage_failure_events": 1, "task_non_success_events": 1, "executor_removed_events": 1}, "task_end_count": 1, "task_end_reasons": [{"reason": "FetchFailed", "count": 1}], "coverage": {"application_start_seen": true, "application_end_seen": true}, "evidence_omitted": 0, "evidence_refs": [{"sha256": "ed369567768e26b937b3f80e42a419c56ed918516b6594cb7e2def0b14f3dbd5", "line": 7}, {"sha256": "ed369567768e26b937b3f80e42a419c56ed918516b6594cb7e2def0b14f3dbd5", "line": 6}, {"sha256": "ed369567768e26b937b3f80e42a419c56ed918516b6594cb7e2def0b14f3dbd5", "line": 5}, {"sha256": "ed369567768e26b937b3f80e42a419c56ed918516b6594cb7e2def0b14f3dbd5", "line": 4}]}
```

| Actual query selection (with base + copied hash) | matched / returned | TaskEnd reasons over full matches | Returned lines; next cursor |
| --- | --- | --- | --- |
| `{"job_id":7}` | 2 / 2 | `[]` | [3, 7]; None |
| `{"execution_id":5}` | 1 / 1 | `[]` | [3]; None |
| `{"stage_id":3,"event_types":["SparkListenerTaskEnd","SparkListenerStageCompleted"],"limit":1}` | 2 / 1 | `[{"reason":"FetchFailed","count":1}]` | [5]; 5 |
| `{"stage_id":3,"event_types":["SparkListenerTaskEnd","SparkListenerStageCompleted"],"limit":1,"after_line":5}` | 2 / 1 | `[{"reason":"FetchFailed","count":1}]` | [6]; None |
| `{"event_types":["SparkListenerJobEnd"]}` | 1 / 1 | `[]` | [7]; None |
| `{"executor_id":"2","event_types":["SparkListenerExecutorRemoved"]}` | 1 / 1 | `[]` | [4]; None |
| `{"stage_id":3,"task_end_reason":"FetchFailed"}` | 1 / 1 | `[{"reason":"FetchFailed","count":1}]` | [5]; None |

**inconclusive** for the requested underlying executor-loss/OOM cause. ExecutorRemoved line 4 says unknown; FetchFailed task line 5, stage failure line 6 and JobFailed line 7 support the observed failure chain. No record supplies OOM or a causal executor exit explanation. Direct executor query confirms unknown; stage reason query confirms FetchFailed. Supporting refs are the four events; opposing evidence for an OOM assertion is the explicit unknown reason, rather than proof that OOM did not happen. Driver/Executor/YARN exit evidence is unavailable and has no bounded external body; no external tool was invented.

### incomplete

Snapshot SHA-256: `13def0da8749db4361d98f9f447d4f43795ae753df3973daf393c6b09a563640`.

Actual inspect/base input:

```json
{"manifest_path": "/private/var/folders/p_/n6lzpss53zv47fjwl9vbhk1m0000gp/T/spark-diagnosis-v4iu9sl3/incomplete/l3/application_1_42/all/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/manifest.json", "attempt_id": null}
```

Verified overview:

```json
{"event_count": 4, "signals": {"job_failed_events": 0, "stage_failure_events": 0, "task_non_success_events": 0, "executor_removed_events": 0}, "task_end_count": 1, "task_end_reasons": [{"reason": "UNKNOWN", "count": 1}], "coverage": {"application_start_seen": true, "application_end_seen": false}, "evidence_omitted": 0, "evidence_refs": []}
```

| Actual query selection (with base + copied hash) | matched / returned | TaskEnd reasons over full matches | Returned lines; next cursor |
| --- | --- | --- | --- |
| `{"job_id":7}` | 1 / 1 | `[]` | [3]; None |
| `{"execution_id":5}` | 1 / 1 | `[]` | [3]; None |
| `{"stage_id":3,"event_types":["SparkListenerTaskEnd","SparkListenerStageCompleted"],"limit":1}` | 1 / 1 | `[{"reason":"UNKNOWN","count":1}]` | [4]; None |
| `{"event_types":["SparkListenerJobEnd"]}` | 0 / 0 | `[]` | []; None |

**inconclusive** for terminal status/root cause: only JobStart line 3 and TaskEnd line 4 appear after the identity prefix. TaskEnd reason is UNKNOWN, not Success or failure; JobEnd query matches zero and ApplicationEnd is absent. A verified scan proves the saved bytes, not upstream completeness. No terminal-state assertion is supported; obtain missing terminal/driver evidence through an available tool or report the gap.

### all_success

Snapshot SHA-256: `45a83aba13e8a06f48eb2f8add4acc0e464e3fa3908a14587399fea8960f23b9`.

Actual inspect/base input:

```json
{"manifest_path": "/private/var/folders/p_/n6lzpss53zv47fjwl9vbhk1m0000gp/T/spark-diagnosis-v4iu9sl3/all_success/l3/application_1_42/all/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/manifest.json", "attempt_id": null}
```

Verified overview:

```json
{"event_count": 7, "signals": {"job_failed_events": 0, "stage_failure_events": 0, "task_non_success_events": 0, "executor_removed_events": 0}, "task_end_count": 1, "task_end_reasons": [{"reason": "Success", "count": 1}], "coverage": {"application_start_seen": true, "application_end_seen": true}, "evidence_omitted": 0, "evidence_refs": [{"sha256": "45a83aba13e8a06f48eb2f8add4acc0e464e3fa3908a14587399fea8960f23b9", "line": 6}, {"sha256": "45a83aba13e8a06f48eb2f8add4acc0e464e3fa3908a14587399fea8960f23b9", "line": 7}]}
```

| Actual query selection (with base + copied hash) | matched / returned | TaskEnd reasons over full matches | Returned lines; next cursor |
| --- | --- | --- | --- |
| `{"job_id":7}` | 2 / 2 | `[]` | [3, 6]; None |
| `{"execution_id":5}` | 1 / 1 | `[]` | [3]; None |
| `{"stage_id":3,"event_types":["SparkListenerTaskEnd","SparkListenerStageCompleted"],"limit":1}` | 2 / 1 | `[{"reason":"Success","count":1}]` | [4]; 4 |
| `{"stage_id":3,"event_types":["SparkListenerTaskEnd","SparkListenerStageCompleted"],"limit":1,"after_line":4}` | 2 / 1 | `[{"reason":"Success","count":1}]` | [5]; None |
| `{"event_types":["SparkListenerJobEnd"]}` | 1 / 1 | `[]` | [6]; None |

**no_observed_failure**, scoped to observed Job 7 and stage/task records. Success task line 4, completed stage line 5 and JobSucceeded line 6 support this; all relevant stage and job-ending records were read and signals show zero observed failure events. The user's failure symptom is not reproduced in this snapshot. ApplicationEnd presence is only observed coverage and cannot prove upstream completeness or YARN/SQL success.

## Fresh verification

- `uv run --locked pytest tests/unit/test_agent_skills.py`: 25 passed.
- `uv run --locked ruff check tests/unit/test_agent_skills.py`: All checks passed.
- `uv run --locked python /Users/liji/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/spark-diagnosis`: Skill is valid.
- `openspec validate add-spark-event-log-inspection --strict`: valid.
- Five actual in-process MCP exercises: 5 inspect calls + 31 query calls; all returned verified results; no classifier asserted conclusions.

Whole-change tests/build/type checking and cross-change/spec validation belong to task 4.1; live network integration is not claimed here.
