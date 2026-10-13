# Task 3.2 verification report

Baseline commit: `899efc8`. Parent completed Apply preflight and gated tasks1.1–3.1. This report covers only task3.2; no OpenSpec completion checkboxes were edited.

## RED and reference controls

Fresh-context baseline probe read unedited Skill before OpenSpec. Present: fetch/inspect/query discovery, snapshot pinning, direct associations, retry/recovery, refs and inconclusive guidance. Absent: both metrics tools, successful slow-job routing, units, per-metric missing counts, nearest-rank, non-additive time, baseline and skew candidate limits. Probe nevertheless independently reasoned correctly: “15 分钟 Stage 无法独立解释48分钟应用”; “不能单凭比例确认根因”. Thus baseline was competent; no manufactured behavioral failure or causal efficacy claim. This extension supplies reference/selection material, not a claimed behavior-shaping intervention. Five-repetition wording micro-tests are not used for this reference-only claim.

Source discovery/contract tests were added before Skill edits. `UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/test_agent_skills.py`: **2 failed,24 passed**, expected failures missing new tool names and performance/long-runtime description. Same command after extension: **26 passed**.

Fresh-context updated probe retrieved correct application→snapshot→Stage→distribution→ref/retry/executor sequence for A/B/C, recognized missing independent cells and candidate/cause limits, no schema mismatch. It flagged omitted-Stage retrieval and possible fault/performance-label ambiguity; minimal refinements now explicitly query Stage IDs for omitted groups and distinguish no_observed_failure from inconclusive performance causes. No pressure-control failure occurred and no behavior improvement is asserted. Full-population statistics are not an instruction to print all tasks.

## Commands and scope

- `UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/contract/test_architecture.py tests/unit/test_agent_skills.py`: **60 passed**.
- `uv run --no-sync ruff check tests/unit/test_agent_skills.py`: **passed**.
- `openspec store list --json`: no stores; no --store applicable.
- `openspec validate add-spark-performance-metrics --strict`: **valid**.
- `openspec validate --changes --strict`: **17 passed,0 failed**; existing INFO notices about unrelated archive targets are not hidden.
- `openspec validate --specs --strict`: **2 passed,0 failed**, existing long-text INFO.
- `git diff --check`: passed.
- Initial nearest-documentation check attempted nonexistent `tests/unit/test_documentation.py`: pytest exit4,0 tests; corrected after `rg --files tests` found no dedicated documentation suite. Architecture and Skill suites above are the actual checks, not a claimed documentation test pass.

## Self-review

Only owned Skill, both READMEs, architecture views, source contract tests and task plan/report changed. Original failure/recovery/unknown/query-truncation/external-evidence guidance preserved. Tool names portable; description triggers-only; no DiagnosisState, fixed query budget, config/dependency/installer/deployment change. Architecture matches SparkMetricsService→SparkInspectionGateway and shared inspector ownership. Final parent whole-change review, fresh validation and checkbox gates remain separate.

# Task 3.2 actual offline FastMCP exercises

Command: `uv run --no-sync /tmp/task-3.2-mcp-replay.py`, exit 0. The standalone harness imports the already installed package, builds production Spark composition with credential-free validated config and private synthetic manifests, dispatches through `StdioMcpServer._fastmcp.call_tool`, and awaits runtime.close in finally. No package reinstall or repository edit. Socket connect/connect_ex are forbidden. This is an in-process MCP application/functional reference probe, not stdio wire verification, live integration, a scaling benchmark, or evidence that the Skill changed an agent's behavior. Full advertised schemas, actual inputs/results and synthetic manifest paths are retained in `/tmp/task-3.2-mcp-results.json`; harness remains replayable. Two successful full executions produced identical content hashes and numerical facts (private fixture paths differ). Initial harness setup failures were corrected: config requires secrets object; macOS private temp paths must resolve; expanded query details require one line and limit=1. None established a backend defect.

All cases: application_1_42, application attempt `1` explicitly selected, Start Timestamp=0 and End Timestamp=2880000 (48 min), verified via query; logs include JobSucceeded. No supplied historical comparator exists, so 48 min is observed elapsed time, not proven abnormal. Every measurement call pins inspect.snapshot.sha256. For each case, call order: inspect; app lifecycle query; overview stage metrics; explicit stage attempt metrics; distribution duration limit1, duration limit20, shuffle limit20, wait limit20; reread every union-ranked Task ref and both lifecycle refs individually with limit1/max_detail_chars32768; query Stage retry/TaskEnd evidence; query executor added/removed evidence. All four distributions asserted equal despite differing order/limit. Individual rereads assert exact digest/line and ranked task identity. 48 successful calls: A16, B15, C17.

| Case | Event count | SHA-256 | Task/lifecycle lines reread |
|---|---:|---|---|
| A |12|1d76f8c92a8b3a2660a0360e956e15a4774b6dca8ee2fc3809cc3c65e9a12b49|5,6,7,8,9,10|
| B |11|2044d18720b35443e64e505e7e3c0705f82660356ac13aab491fd631a94b098c|5,6,7,8,9|
| C |16|8da348f14b9183583b803b69535ca6743be509454399f5cc81f96e69c4bbc88e|5,8,10,11,12,13,14|

Refs below mean `{sha256: case hash above, line: stated line}`. Quantiles are nearest-rank, not interpolated. Success TaskEnd events are separate attempt samples, not logically deduplicated work. All omitted ranks and per-metric missing cells remain explicit.

## A — long tail and large Shuffle co-occur

Stage17/0 [200000,1100000], duration900000ms; submitted ref5/completed ref10. Counts total/success/non-success/unknown=4/4/0/0; Input total400000000 bytes, Shuffle total1200000000 bytes; both valid4/missing0. Tasks1/2/3 refs6/7/8 duration100000ms, Shuffle100000000bytes, wait10000ms each. Task4 ref9 duration900000ms and Shuffle900000000bytes, wait10000ms. Duration min/p50/p95/max=100000/100000/900000/900000; Shuffle=100000000/100000000/900000000/900000000. All six metric distributions valid4/missing0; GC all1000ms, Input all100000000bytes. Duration limit1 ranked4/omitted3; limit20 ranked4/omitted0; shuffle/wait order ranked4/omitted0. Wait ties rank refs6,7,8,9, demonstrating an alternate ordering that need not put the slow task first while full-sample p95 remains intact.

Manual conclusion: same Task4 is both 9x duration and 9x Shuffle versus observed peers, supporting a data-volume/skew candidate. No partition-key distribution, operator plan, comparable baseline or external executor evidence confirms skew. Similar low Fetch Wait is counterevidence to a wait-dominated explanation for this case. Executor-added is observed, no removed event is observed; absence is limited to this complete synthetic snapshot. JobSucceeded does not close the slow-job investigation. Stage interval covers only900000ms; application time outside observed Stage interval is1980000ms (33min), unexplained. Task/GC/wait/run metrics must not be added as application elapsed components.

## B — similar bytes with high Fetch Wait

Stage17/0 same interval/duration as A, refs5/9. Counts3/3/0/0. Input and Shuffle totals300000000 bytes, each valid3/missing0. Tasks1/2 refs6/7 duration100000ms, wait10000ms; Task3 ref8 duration900000ms, wait700000ms. All tasks Input=Shuffle=100000000bytes. Duration min/p50/p95/max=100000/100000/900000/900000; Shuffle all100000000; wait min/p50/p95/max=10000/10000/700000/700000. All metric counts3/0. Limit1 duration ranked3/omitted2; limit20 duration/shuffle/wait ranked3/omitted0. Shuffle ties select refs6,7,8; wait selects8,6,7.

Manual conclusion: comparable observed bytes and same slow Task3's high Fetch Wait support a Shuffle-fetch waiting candidate and weaken simple greater-byte-volume explanation. 700000/900000 is an observation, not an additive time decomposition or network-failure proof. No transport diagnostics, remote executor health, resource scheduling or independent cluster evidence confirms the cause. No executor removal is observed. GC1000ms everywhere supplies no strong GC candidate. Unaccounted app time1980000ms remains a gap, as in A.

## C — retry and independent missing cells

Overview matched2 stage attempts, omitted0, unassigned TaskEnd0. Stage17/0 [100000,200000], duration100000ms refs5/8, counts1/0/1/0, Input/Shuffle totalnull valid0/missing0. Failed task90 ref6 has FetchFailed; completed Stage ref8 has explicit synthetic failure reason. Executor2 removal ref7 Timestamp200000 reason says synthetic lost/cause unknown; re-add ref9 Timestamp250000. Stage17/1 [300000,1200000], duration900000ms refs10/14, counts3/3/0/0. Explicit distribution selects attempt1 only. Input total300000000 valid3/missing0; Shuffle total1000000000 valid2/missing1.

Success tasks1/2/3 refs11/12/13: duration100000/null/900000 and Shuffle null/100000000/900000000. These are independent missing cells; they do not eliminate the whole row. Duration valid2/missing1 min/p50/p95/max=100000/100000/900000/900000; Shuffle valid2/missing1=100000000/100000000/900000000/900000000. Other metrics valid3/missing0; executor run min50000/p50100000/p95900000/max900000; GC1000, Input100000000, wait10000 each. Duration limit1 ranked2/omitted1, duration limit20 ranked2/omitted0; shuffle ranked2/omitted0 and wait ranked3/omitted0, bringing ref12 back into view. Missing-order samples are excluded from ranking and disclosed through missing_count, not counted as omitted ranked rows.

Manual conclusion: failed Stage0 then successful Stage1 establishes observed recovery and keeps the failure facts useful. FetchFailed + executor removal are factual observations; their co-occurrence and explicitly unknown removal reason do not establish network failure/OOM or the direction of causality. Success-attempt distributions do not mix failed-task measurements. Partial success cells prevent complete duration-to-Shuffle comparison across all tasks; only task3 has both long duration and large Shuffle. Stage observed intervals are disjoint in this fixture; union length1000000ms, leaving1880000ms of app span outside them. This fixture-specific interval calculation is not a general license to add overlapping Stage durations or infer critical path. Need further task retries/speculation identity and operator/executor evidence to confirm a candidate.

## Limitations and manual verdict

Passed: real exposed dispatch/schema, pin/explicit attempts, stage separation, 48-minute lifecycle query, full-success stats independent of list limits/order, exact ref rereads, retry/executor queries, independent metric availability, no-network boundary and awaited cleanup. Not tested here: wire transport, live backend, large evidence runtime/memory, cancellation/error regression, historical abnormality, or Skill behavior-shaping effectiveness. Those remain separate acceptance evidence. The probe provides deterministic reference facts and honest candidate/counterevidence/gap conclusions; it does not claim synthetic production causes or prove an agent followed the Skill.

## Exact actual call inputs

Each case below defines M as the recorded private synthetic manifest path and H as its fixed sanitized digest. Every input below is the actual input with those two literal values replaced by aliases for readability; all other supplied fields are unchanged. Runtime closes and temporary fixtures are deleted after replay. The controlling agent independently reran the same harness successfully after final documentation edits; hashes/counts/refs were unchanged. Full result JSON and schemas remain `/tmp/task-3.2-mcp-results.json`; replay creates new private paths with the same hashes.

### Case A

M=`/private/var/folders/p_/n6lzpss53zv47fjwl9vbhk1m0000gp/T/task-3.2-A-lvnvf25o/application_1_42/all/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/manifest.json`

H=`1d76f8c92a8b3a2660a0360e956e15a4774b6dca8ee2fc3809cc3c65e9a12b49`

1. `inspect_spark_event_log`: `{"manifest_path":"M","attempt_id":"1"}`
2. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","event_types":["SparkListenerApplicationStart","SparkListenerApplicationEnd"]}`
3. `get_spark_stage_metrics`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H"}`
4. `get_spark_stage_metrics`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","stage_id":17,"stage_attempt_id":0}`
5. `get_spark_task_distribution`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","stage_id":17,"stage_attempt_id":0,"order_by":"duration_ms","limit":1}`
6. `get_spark_task_distribution`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","stage_id":17,"stage_attempt_id":0,"order_by":"duration_ms","limit":20}`
7. `get_spark_task_distribution`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","stage_id":17,"stage_attempt_id":0,"order_by":"shuffle_read_bytes","limit":20}`
8. `get_spark_task_distribution`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","stage_id":17,"stage_attempt_id":0,"order_by":"shuffle_fetch_wait_ms","limit":20}`
9. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","lines":[5],"limit":1,"max_detail_chars":32768}`
10. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","lines":[6],"limit":1,"max_detail_chars":32768}`
11. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","lines":[7],"limit":1,"max_detail_chars":32768}`
12. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","lines":[8],"limit":1,"max_detail_chars":32768}`
13. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","lines":[9],"limit":1,"max_detail_chars":32768}`
14. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","lines":[10],"limit":1,"max_detail_chars":32768}`
15. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","stage_id":17,"event_types":["SparkListenerTaskEnd","SparkListenerStageSubmitted","SparkListenerStageCompleted"],"max_detail_chars":2048}`
16. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","executor_id":"2","event_types":["SparkListenerExecutorAdded","SparkListenerExecutorRemoved"],"max_detail_chars":2048}`

Named public results verified: SparkEventLogInspectionResult, SparkEventQueryResult, SparkStageMetricsResult and SparkTaskDistributionResult via actual FastMCP structured output; these are not direct gateway calls.

### Case B

M=`/private/var/folders/p_/n6lzpss53zv47fjwl9vbhk1m0000gp/T/task-3.2-B-0_ah4dxl/application_1_42/all/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/manifest.json`

H=`2044d18720b35443e64e505e7e3c0705f82660356ac13aab491fd631a94b098c`

1. `inspect_spark_event_log`: `{"manifest_path":"M","attempt_id":"1"}`
2. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","event_types":["SparkListenerApplicationStart","SparkListenerApplicationEnd"]}`
3. `get_spark_stage_metrics`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H"}`
4. `get_spark_stage_metrics`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","stage_id":17,"stage_attempt_id":0}`
5. `get_spark_task_distribution`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","stage_id":17,"stage_attempt_id":0,"order_by":"duration_ms","limit":1}`
6. `get_spark_task_distribution`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","stage_id":17,"stage_attempt_id":0,"order_by":"duration_ms","limit":20}`
7. `get_spark_task_distribution`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","stage_id":17,"stage_attempt_id":0,"order_by":"shuffle_read_bytes","limit":20}`
8. `get_spark_task_distribution`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","stage_id":17,"stage_attempt_id":0,"order_by":"shuffle_fetch_wait_ms","limit":20}`
9. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","lines":[5],"limit":1,"max_detail_chars":32768}`
10. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","lines":[6],"limit":1,"max_detail_chars":32768}`
11. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","lines":[7],"limit":1,"max_detail_chars":32768}`
12. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","lines":[8],"limit":1,"max_detail_chars":32768}`
13. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","lines":[9],"limit":1,"max_detail_chars":32768}`
14. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","stage_id":17,"event_types":["SparkListenerTaskEnd","SparkListenerStageSubmitted","SparkListenerStageCompleted"],"max_detail_chars":2048}`
15. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","executor_id":"2","event_types":["SparkListenerExecutorAdded","SparkListenerExecutorRemoved"],"max_detail_chars":2048}`

Named public results verified: SparkEventLogInspectionResult, SparkEventQueryResult, SparkStageMetricsResult and SparkTaskDistributionResult via actual FastMCP structured output; these are not direct gateway calls.

### Case C

M=`/private/var/folders/p_/n6lzpss53zv47fjwl9vbhk1m0000gp/T/task-3.2-C-hu33q0uk/application_1_42/all/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/manifest.json`

H=`8da348f14b9183583b803b69535ca6743be509454399f5cc81f96e69c4bbc88e`

1. `inspect_spark_event_log`: `{"manifest_path":"M","attempt_id":"1"}`
2. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","event_types":["SparkListenerApplicationStart","SparkListenerApplicationEnd"]}`
3. `get_spark_stage_metrics`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H"}`
4. `get_spark_stage_metrics`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","stage_id":17,"stage_attempt_id":1}`
5. `get_spark_task_distribution`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","stage_id":17,"stage_attempt_id":1,"order_by":"duration_ms","limit":1}`
6. `get_spark_task_distribution`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","stage_id":17,"stage_attempt_id":1,"order_by":"duration_ms","limit":20}`
7. `get_spark_task_distribution`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","stage_id":17,"stage_attempt_id":1,"order_by":"shuffle_read_bytes","limit":20}`
8. `get_spark_task_distribution`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","stage_id":17,"stage_attempt_id":1,"order_by":"shuffle_fetch_wait_ms","limit":20}`
9. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","lines":[5],"limit":1,"max_detail_chars":32768}`
10. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","lines":[8],"limit":1,"max_detail_chars":32768}`
11. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","lines":[10],"limit":1,"max_detail_chars":32768}`
12. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","lines":[11],"limit":1,"max_detail_chars":32768}`
13. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","lines":[12],"limit":1,"max_detail_chars":32768}`
14. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","lines":[13],"limit":1,"max_detail_chars":32768}`
15. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","lines":[14],"limit":1,"max_detail_chars":32768}`
16. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","stage_id":17,"event_types":["SparkListenerTaskEnd","SparkListenerStageSubmitted","SparkListenerStageCompleted"],"max_detail_chars":2048}`
17. `query_spark_events`: `{"manifest_path":"M","attempt_id":"1","expected_sha256":"H","executor_id":"2","event_types":["SparkListenerExecutorAdded","SparkListenerExecutorRemoved"],"max_detail_chars":2048}`

Named public results verified: SparkEventLogInspectionResult, SparkEventQueryResult, SparkStageMetricsResult and SparkTaskDistributionResult via actual FastMCP structured output; these are not direct gateway calls.
