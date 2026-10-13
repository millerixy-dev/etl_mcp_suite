## Purpose

Provide reproducible offline Stage-attempt rankings and bounded Task metric distributions from a fixed Spark event-log snapshot, allowing an agent to select further evidence and explain performance observations without server-side diagnosis state or causal classification.

## ADDED Requirements

### Requirement: Contribute two offline performance fact tools
This capability SHALL contribute exactly get_spark_stage_metrics and get_spark_task_distribution to the Spark plugin, preserving existing tool contracts. The process SHALL expose the exact union of implemented Spark capabilities and no other plugin tools. Performance calls MUST NOT access the network, refresh evidence, persist aggregates or manage diagnosis sessions.

#### Scenario: Reuse private evidence offline
- **GIVEN** matching local evidence and valid Spark configuration without credentials or reachable upstream
- **WHEN** a performance tool is invoked
- **THEN** its named result is returned locally without network access or evidence mutation

#### Scenario: Compose the delivered tools
- **GIVEN** download, inspection and performance capabilities are implemented
- **WHEN** tools are listed
- **THEN** their five-tool union is exposed, plus only tools contributed by other actually implemented Spark capabilities

### Requirement: Bind facts to one verified snapshot
Both tools SHALL require manifest_path, explicit nullable application attempt_id and expected_sha256 under the strict types and ranges in design.md. Null SHALL select only an actual null-attempt entry. Both SHALL verify selected private evidence, source, format, size, digest, event count and identity before returning. The expected digest SHALL match the sanitized JSONL. Invalid inputs SHALL return INVALID_INPUT, missing evidence/selected manifest attempt NOT_FOUND and corrupt/conflicting evidence UNEXPECTED_RESPONSE. Partial results MUST NOT be published.

#### Scenario: Reject evidence changed after inspection
- **GIVEN** the caller pins an earlier sanitized digest
- **WHEN** current evidence conflicts with that digest, including after a ranking has enough candidates
- **THEN** the tool fails safely without returning aggregates or replacement evidence

#### Scenario: Reject ambiguous or coercible input
- **GIVEN** bool/string numeric IDs, an unknown ordering value, extra arguments or only one optional Stage identifier
- **WHEN** inputs are validated
- **THEN** INVALID_INPUT is returned without scanning or echoing rejected values

### Requirement: Define success-attempt samples and unknown measurements
Task classification SHALL cover matched TaskEnd events, using task_end_count, successful_task_end_count, non_success_task_end_count and unknown_reason_task_end_count. Only explicitly valid Reason=Success events SHALL contribute performance samples. Retries and speculative attempts SHALL remain separate event samples without logical-workload deduplication. The six metrics, strict numeric validity, timestamp subtraction and complete Shuffle-component summation SHALL follow design.md. Missing/invalid measurements SHALL remain unknown, never implicit zero. Each metric SHALL report valid_count and missing_count whose sum equals its successful sample count.

#### Scenario: Separate failed attempts from successful measurements
- **GIVEN** a failed task attempt, a successful retry and a speculative successful attempt
- **WHEN** measurements are calculated
- **THEN** classification includes all three events, while two successful attempts contribute samples without claiming two distinct logical partitions

#### Scenario: Preserve partial metric availability
- **GIVEN** a successful TaskEnd has valid timestamps, missing Task Metrics and another has a missing Shuffle component
- **WHEN** either tool summarizes it
- **THEN** available measurements remain usable, unavailable measurements increase missing_count and no missing component is replaced with zero

#### Scenario: Keep zero distinct from absent values
- **GIVEN** an explicit zero measurement and a missing measurement
- **WHEN** summaries are returned
- **THEN** zero contributes a valid sample while the missing value does not, and an empty valid sample returns null statistics

### Requirement: Return ranked Stage attempts with disclosed omissions
get_spark_stage_metrics SHALL accept the shared inputs, optional paired stage_id/stage_attempt_id and limit in design.md. It SHALL return SparkStageMetricsResult with exactly snapshot, coverage, matched_stage_attempt_count, unassigned_task_end_count, stages and stages_omitted. Groups SHALL use only explicit valid Stage/attempt fields from lifecycle and TaskEnd events. Lifecycle source selection, duration calculation, fixed row fields and Input/Shuffle MetricTotal SHALL follow design.md. Task counts and sums SHALL cover the full selected group before ranking; unassignable TaskEnd count SHALL describe the entire file regardless of Stage filter. Rows SHALL rank by valid duration descending then Stage/attempt ascending, put null durations last and return at most limit. Counts and omissions SHALL disclose the pre-limit population. No match SHALL return an empty successful result.

#### Scenario: Keep Stage retry attempts separate
- **GIVEN** Stage 17 attempts 0 and 1 with overlapping lifetimes and a TaskEnd lacking valid Stage attempt identity
- **WHEN** the overview is requested
- **THEN** attempts are separate rows, the unassignable event is disclosed and no duration sum is labeled application elapsed time

#### Scenario: Keep unfinished or task-only groups observable
- **GIVEN** one group has TaskEnd only and another has lifecycle timestamps missing or in reverse order
- **WHEN** rankings are returned
- **THEN** their durations are null, available TaskEnd facts remain visible and no terminal status is invented

#### Scenario: Recover an omitted Stage by explicit selection
- **GIVEN** more groups than limit and tied durations
- **WHEN** the caller requests rankings and later an explicitly identified Stage attempt
- **THEN** ordering/omitted counts are deterministic and the explicit selection returns that group's complete counters and totals

### Requirement: Return fixed distributions and correlated ranked tasks
get_spark_task_distribution SHALL require the shared snapshot and Stage/attempt identifiers, accepting only the fixed order_by enum and limit in design.md. It SHALL return SparkTaskDistributionResult with exactly snapshot, coverage, stage_id, stage_attempt_id, four TaskEnd classification counts, distributions, order_by, ranked_task_count, top_tasks and tasks_omitted. Distributions SHALL contain exactly the six MetricDistribution fields and fixed min/p50/p95/max using nearest-rank, with independent valid/missing counts over all successful samples before ranking. Only samples with a valid ordering measurement SHALL enter top_tasks, ordered by measurement descending and physical line ascending. Each ranked row SHALL contain direct nullable task_id/executor_id, a TaskEnd ref and all six nullable metric values. Ranked/omitted counts SHALL disclose the pre-limit ranking population. Empty populations SHALL return zero counts, null statistics and empty lists.

#### Scenario: Keep tail statistics independent of the displayed list
- **GIVEN** a long-tail successful task lies beyond a limit chosen under another ordering
- **WHEN** distributions are returned
- **THEN** all successful samples contribute their valid measurements and changing ordering/limit does not change the distributions

#### Scenario: Use deterministic nearest-rank quantiles
- **GIVEN** duration measurements 100 and 900 plus one missing successful duration
- **WHEN** a distribution is returned
- **THEN** valid_count=2, missing_count=1, min=p50=100 and p95=max=900 without interpolation

#### Scenario: Select tasks for comparing related measurements
- **GIVEN** successful tasks differ in duration and Shuffle Read
- **WHEN** either metric orders the ranked list
- **THEN** each selected row includes both values and the other fixed metrics, with exact refs suitable for query_spark_events rereading

#### Scenario: Handle absent successes without inventing performance
- **GIVEN** only non-success or unknown TaskEnd events match the selected Stage attempt
- **WHEN** distributions are requested
- **THEN** classification remains observable, each distribution has zero valid/missing counts and null statistics, and top_tasks is empty

### Requirement: Keep provenance and runtime safety intact
Results SHALL use the existing snapshot and full-file coverage shapes, sanitized digest and physical-line refs. Aggregate scope SHALL be reproducible from snapshot, explicit Stage/attempt, fixed sampling policy and population counts, not falsely attributed to a single event. Configured size limits, original total deadline, private cache ownership, credential redaction and safe error categories SHALL apply. Cancellation, timeout and shutdown SHALL await owned work and release resources without partial results. stdout SHALL contain MCP protocol only; configured secrets, raw exceptions and arbitrary event bodies MUST NOT enter results or diagnostics.

#### Scenario: Reread a ranked task
- **GIVEN** a returned TaskEnd ref and unchanged evidence
- **WHEN** query_spark_events rereads its line with the same manifest/attempt/expected digest
- **THEN** the source event matches the ranked row's direct identity and measurements

#### Scenario: Cancel aggregate computation
- **GIVEN** an owned scan or calculation is cancelled or exceeds its original deadline
- **WHEN** cleanup executes
- **THEN** owned work/resources are closed before directory ownership is released, with no partial successful result and a safe operation-specific timeout where applicable

### Requirement: Extend the agent-owned slow-job evidence loop
The existing spark-diagnosis Skill SHALL guide application-time verification through query, fixed-snapshot Stage ranking, selected Stage-attempt distribution, Task ref rereading, and checking retry/executor/other available evidence. It SHALL keep facts, hypotheses, support, counterevidence and gaps in the host agent's working context without DiagnosisState. It MUST NOT label runtime abnormal without an actual supplied comparison, sum overlapping Stage durations as application time, equate JobSucceeded with absence of performance problems, or assert a root cause from a lone metric, ranking or ratio. Reports SHALL disclose sample scope, missing measurements, omitted rankings and causal limitations.

#### Scenario: Investigate a long runtime without a historical baseline
- **GIVEN** the user asks why an application took 48 minutes with no comparable baseline
- **WHEN** the Skill follows the evidence loop
- **THEN** it explains observed time/Stage/Task facts and checks candidate causes without declaring the runtime statistically abnormal

#### Scenario: Distinguish a skew candidate from a confirmed cause
- **GIVEN** long tasks also read more Shuffle bytes
- **WHEN** the agent assesses distributions and task refs
- **THEN** it treats skew as a candidate requiring further evidence, rather than a tool-certified root cause

#### Scenario: Keep waiting and missing-data candidates honest
- **GIVEN** similar observed data sizes, elevated Fetch Wait, retries and some missing metrics
- **WHEN** the Skill investigates
- **THEN** it checks task/executor/recovery evidence, preserves unknown measurements and does not assert network failure or OOM without supporting evidence
