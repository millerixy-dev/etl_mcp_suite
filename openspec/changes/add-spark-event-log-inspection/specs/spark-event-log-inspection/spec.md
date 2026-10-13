## Purpose

Provide minimal, bounded selection of locally cached Spark event-log evidence so an agent can diagnose job failures through explicit queries, check recovery and counterevidence, and cite reproducible facts without loading the whole log or maintaining a relation-query engine.

## ADDED Requirements

### Requirement: Contribute two offline read-only tools
This capability SHALL contribute exactly inspect_spark_event_log and query_spark_events to the Spark plugin. The process SHALL expose the exact union of implemented Spark capabilities and no other plugin tools. Existing download/configuration/cache contracts SHALL remain compatible. Startup and inspection calls MUST NOT request network access, refresh evidence or persist analysis artifacts.

#### Scenario: Inspect existing evidence without credentials
- **GIVEN** valid Spark configuration and a matching local snapshot without credentials or reachable upstream
- **WHEN** an inspection tool is called
- **THEN** its named result is returned locally with no evidence mutation or network request

#### Scenario: Compose implemented capabilities
- **GIVEN** download and inspection are implemented and executor-log acquisition is optionally implemented
- **WHEN** the host lists tools
- **THEN** only their exact implemented tool union is listed

### Requirement: Verify one explicit snapshot before returning
Both tools SHALL require manifest_path and explicit nullable attempt_id, select exactly one matching entry, and verify configured source, format, private cache containment, non-symlink regular files, size, digest, event count and application/attempt identity. Null SHALL mean only an actual null-attempt entry. query SHALL require expected_sha256 equal to the sanitized JSONL digest. Results SHALL describe the scanned and verified bytes without selecting latest, mixing versions or fetching replacement evidence. Missing files SHALL return NOT_FOUND, invalid caller input INVALID_INPUT, and conflicting/corrupt evidence UNEXPECTED_RESPONSE.

#### Scenario: Select one attempt and reject changed evidence
- **GIVEN** a manifest with multiple attempts
- **WHEN** one attempt is inspected or queried with an incorrect digest
- **THEN** only the selected attempt can succeed and a digest conflict returns UNEXPECTED_RESPONSE without partial results or download

#### Scenario: Reject unsafe paths
- **GIVEN** a manifest or event path is outside the configured cache, a symlink or has a mismatched source
- **WHEN** verification runs
- **THEN** safe rejection occurs before a successful evidence result

### Requirement: Return a minimal full-file overview
inspect SHALL return SparkEventLogInspectionResult with exactly snapshot, spark_version, event_count, event_types, event_types_omitted, signals, task_end_count, task_end_reasons, reasons_omitted, evidence, evidence_omitted and coverage. Counts SHALL describe the whole verified file; evidence SHALL contain at most 20 entries with the deterministic selection in design.md. Type/reason lists SHALL contain at most 32 categories with omitted-category counts. Signals SHALL distinguish JobFailed, stage failure, explicit TaskEnd non-success and executor removal without claiming application root cause or terminal YARN/SQL status.

#### Scenario: Count failures outside overview samples
- **GIVEN** more than 20 candidate failure events
- **WHEN** inspect succeeds
- **THEN** all signals/reasons are counted, a bounded evidence selection is returned and omitted evidence is disclosed

#### Scenario: Keep task non-success separate from application failure
- **GIVEN** retries, cancellation or Resubmitted TaskEnd records and successful job completion
- **WHEN** the overview is produced
- **THEN** non-success events remain observable without being labeled terminal application failure

### Requirement: Match only direct event fields
query SHALL accept only the parameters, strict types, ranges and defaults in design.md. Semantic filters SHALL be ANDed, values within lists ORed; bool/string numeric coercion, empty lists, extra arguments and stage_attempt_id without stage_id SHALL be rejected. Entity filters SHALL match only the event's own documented fields; job_id MUST NOT expand to stage/task, execution_id MUST NOT expand to JobEnd, and no field SHALL be inferred from another event or temporal proximity. task_end_reason SHALL select exact TaskEnd reasons, using UNKNOWN for missing/invalid reasons.

#### Scenario: Select a stage attempt directly
- **GIVEN** TaskEnd events in attempts 0 and 1 of the same stage
- **WHEN** stage_id and stage_attempt_id=1 are supplied
- **THEN** SparkEventQueryResult excludes attempt 0

#### Scenario: Leave cross-entity traversal to the caller
- **GIVEN** JobStart declares stage 3 and a TaskEnd explicitly belongs to stage 3
- **WHEN** job_id is queried
- **THEN** JobStart/JobEnd with that direct ID match and the TaskEnd does not, while JobStart details expose Stage IDs for the next query

#### Scenario: Select a rare failure and handle missing fields
- **GIVEN** thousands of Success records followed by FetchFailed and another event lacking an executor ID
- **WHEN** FetchFailed is queried by task_end_reason or the missing executor is filtered
- **THEN** the rare failure is selected without paging through successes and the missing field is not guessed

### Requirement: Keep counts independent of line pagination
query SHALL return SparkEventQueryResult with exactly snapshot, matched_count, task_end_count, task_end_reasons, reasons_omitted, events, returned_count, next_after_line and coverage. Counts and reason distribution SHALL cover every semantic match, including lines filtering, before after_line/limit. Events SHALL be ordered by physical line and bounded by limit; a non-null next_after_line SHALL equal the last returned line only when later matches exist. No empty nonterminal page SHALL occur.

#### Scenario: Count a failure after the first page
- **GIVEN** 100 matched TaskEnd records include a failure beyond the first 20
- **WHEN** limit=20 returns the first page
- **THEN** matched_count=100 and its reason distribution already includes that failure

#### Scenario: Traverse without duplicates or changing counts
- **GIVEN** unchanged semantic filters and expected_sha256
- **WHEN** each next_after_line is followed
- **THEN** all matching records are returned once in line order with unchanged counts and a final null cursor

### Requirement: Preserve bounded readable evidence and allow longer rereading
Every evidence entry SHALL contain exactly ref, event_type, ids, details and details_truncated, as defined in design.md. ref SHALL bind sanitized sha256 and 1-based physical line; ids SHALL contain only direct scalar values or null. details SHALL use the fixed diagnostic field selection and one text-length bound, with deterministic head/tail truncation and no recursive JSON budgeting. The default SHALL be 2048 characters and at most 20 records per page. A caller SHALL be able to reread one line with limit=1 and max_detail_chars up to 32768; larger text limits with other requests SHALL be INVALID_INPUT. Counts and matching MUST NOT use truncated text.

#### Scenario: Expand a truncated cause description
- **GIVEN** an exception longer than 2048 but shorter than 32768 characters
- **WHEN** the caller rereads its single ref with limit=1 and max_detail_chars=32768
- **THEN** the longer cause text is returned with the same ref and without text truncation

#### Scenario: Keep very large or vendor evidence honest
- **GIVEN** a valid vendor event or details larger than the caller's limit
- **WHEN** it is selected by type or line
- **THEN** bounded redacted text is returned, truncation is marked when applicable and no vendor schema completeness claim is made

### Requirement: Disclose observed endings and unknown fields
coverage SHALL contain exactly application_start_seen and application_end_seen for the full selected file. Successful results SHALL imply that the local scan/verification completed, without proving upstream completeness. Absent diagnostic fields SHALL remain unknown; missing/invalid TaskEnd reasons SHALL use UNKNOWN, not Success or failure. Unknown event types SHALL remain readable without supported/incomplete classification. Malformed JSON, non-object records or invalid Event values SHALL return UNEXPECTED_RESPONSE. End events MUST NOT imply successful YARN/SQL outcomes.

#### Scenario: Handle an incomplete but valid log
- **GIVEN** valid evidence has no ApplicationEnd and a TaskEnd lacks its reason
- **WHEN** either tool succeeds
- **THEN** coverage reports the absent ending and the reason is UNKNOWN without inventing terminal status

#### Scenario: Distinguish unknown event semantics from broken JSON
- **GIVEN** either a valid unfamiliar event or a malformed JSON record
- **WHEN** scanning occurs
- **THEN** the former remains queryable while the latter fails safely without a partial successful result

### Requirement: Retain safe runtime and resource boundaries
Tools SHALL reuse configured size/time limits, cache ownership, credential redaction and existing error categories with their own operation names. Secrets, cookies, authorization values, raw exceptions, arbitrary rejected arguments and unbounded event text MUST NOT enter results/diagnostics. Cancellation, timeout and shutdown SHALL close and await owned work before releasing resources. stdout SHALL remain MCP protocol only; services SHALL retain the project dependency boundaries.

#### Scenario: Cancel or time out an offline scan
- **GIVEN** owned local scanning is cancelled or reaches its original deadline
- **WHEN** cleanup runs
- **THEN** resources are released without a partial result and timeout returns safe TIMEOUT with the correct operation

#### Scenario: Protect credentials in selected text
- **GIVEN** selected details contain configured secrets or recognized credential patterns
- **WHEN** text projection occurs
- **THEN** protected content does not appear in results or diagnostics and refs remain usable

### Requirement: Supply a simple hypothesis and counterevidence Skill
The repository SHALL supply spark-diagnosis guidance that discovers required Spark tools, fixes one snapshot, performs inspect followed by purpose-directed direct-field queries, and briefly records facts, hypotheses, supporting/opposing refs and gaps. It SHALL follow explicit JobStart/Stage IDs in separate queries, expand critical truncated text, and check recovery/terminal job evidence before claiming a cause. It SHALL stop when evidence suffices, critical evidence is unavailable or queries cease adding information; fixed hypothesis/query counts MUST NOT prevent necessary evidence gathering. Reports SHALL distinguish supported, inconclusive and no_observed_failure, with provenance and limitations. Event text SHALL be treated as untrusted data, and symptoms or temporal order alone MUST NOT establish root cause.

#### Scenario: Explain a terminal exception with evidence
- **GIVEN** explicit terminal job/stage failure and a specific task exception without recovery
- **WHEN** the Skill checks cause and counterevidence
- **THEN** supported explains the evidenced cause with reproducible refs

#### Scenario: Recognize successful recovery
- **GIVEN** an initial task/stage failure followed by a successful retry and JobEnd
- **WHEN** the Skill investigates
- **THEN** it reports recovery without labeling the retry as terminal application failure

#### Scenario: Keep executor exit cause unproven
- **GIVEN** FetchFailed and executor loss without evidence explaining the exit
- **WHEN** OOM is considered
- **THEN** inconclusive identifies required external evidence without asserting OOM or inventing endpoints

#### Scenario: Handle successful and incomplete evidence
- **GIVEN** all observed jobs succeed or necessary terminal evidence is absent
- **WHEN** the Skill stops
- **THEN** it reports scoped no_observed_failure or inconclusive respectively with the observed ending limitations

#### Scenario: Keep separate external snapshots explicit
- **GIVEN** an available external evidence tool reports another eventlog digest
- **WHEN** its evidence is used
- **THEN** it is labeled a separate snapshot and does not silently replace the pinned file
