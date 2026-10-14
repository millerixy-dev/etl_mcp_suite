## Purpose

Provide a read-only Spark executor and Driver log acquisition tool that resolves container log URLs from verified event-log evidence, accesses an explicitly configured gateway, and saves bounded redacted stdout or stderr as private local diagnostic evidence without exposing credentials or accepting arbitrary network targets.

## ADDED Requirements

### Requirement: Expose one executor log fetch tool with explicit identity
The Spark plugin SHALL expose `fetch_spark_executor_log(application_id: string, attempt_id: string, executor_id: string, log_type: "stdout" | "stderr" = "stderr", tail_bytes: integer = 65536)`. application_id SHALL match ASCII `application_[0-9]+_[0-9]+` with at most 128 characters; attempt_id SHALL match `[1-9][0-9]{0,9}`; executor_id SHALL be `driver`, `0`, or `[1-9][0-9]{0,19}`. tail_bytes SHALL be a strict integer in 1–1048576 with a fixed 1 MiB ceiling. Boolean and string coercion, unknown arguments, caller URLs, paths, arbitrary log names, credentials, headers, and TLS controls MUST be rejected before acquisition with safe INVALID_INPUT. This capability SHALL contribute exactly `fetch_spark_executor_log`. The process SHALL register the exact union of implemented Spark capabilities, including `fetch_spark_event_log`, without another plugin's tools or startup network access.

#### Scenario: Fetch one executor stderr tail
- **GIVEN** valid enabled configuration and an exact application, attempt and executor request
- **WHEN** fetch_spark_executor_log is called without log_type or tail_bytes
- **THEN** it requests that executor's stderr tail of at most 65536 source bytes and returns SparkExecutorLogFetchResult after verified publication

#### Scenario: Fetch the Driver stdout shown in the UI
- **GIVEN** a caller explicitly selects executor_id=driver and log_type=stdout
- **WHEN** the tool resolves the requested attempt
- **THEN** Driver Logs supplies the URL and SparkExecutorLogFetchResult.executor_id is driver

#### Scenario: Reject ambiguous or coerced inputs
- **GIVEN** a missing/null attempt, a string or boolean tail_bytes, a syslog log_type or an undeclared URL/credential argument
- **WHEN** raw MCP or service validation runs
- **THEN** INVALID_INPUT is returned with no file mutation, network request or echoed argument value

#### Scenario: Start using an existing eventlog-only configuration
- **GIVEN** a previously valid Spark configuration without executor log gateway fields and an unreachable upstream
- **WHEN** the stdio process starts and lists tools
- **THEN** the exact union of implemented Spark capability tools registers locally, existing eventlog requests retain their contract, and executor-log calls return CONFIG_ERROR before acquisition

### Requirement: Resolve real container URLs from matching event-log evidence
The tool SHALL obtain verified event-log evidence matching configured History Server source and exact application/attempt, reusing valid local eventlog evidence or using the existing eventlog acquisition contract. Driver URLs SHALL come from SparkListenerApplicationStart.Driver Logs; executor URLs SHALL come from the last matching SparkListenerExecutorAdded.Executor Info.Log Urls. Container application and attempt, owner and stream SHALL be validated against the request and event evidence. It MUST NOT select latest or another attempt, compute a container ID from executor ID, substitute the login identity for the URL owner, or derive NodeId ports from Spark addresses. Missing executor/stream evidence SHALL return NOT_FOUND without an automatic full eventlog refresh; callers can explicitly refresh through the existing eventlog tool. Corrupt evidence and unsafe or identity-conflicting URLs SHALL return UNEXPECTED_RESPONSE without a container-log request.

#### Scenario: Resolve the last executor registration
- **GIVEN** verified exact-attempt evidence contains two registration events for the same executor
- **WHEN** its selected stream is requested
- **THEN** the last registration is used and its actual URL/container identity is validated without merging registrations

#### Scenario: Report an executor missing from cached evidence
- **GIVEN** valid cached evidence lacks the selected executor or stream
- **WHEN** the tool resolves the request
- **THEN** NOT_FOUND is returned without a second eventlog download, and a safe explanation identifies explicit eventlog refresh as the next action

#### Scenario: Reject a mismatched container
- **GIVEN** a selected event URL contains a container from another application or attempt
- **WHEN** identity validation runs
- **THEN** UNEXPECTED_RESPONSE is returned before contacting a log endpoint

#### Scenario: Preserve completed evidence and report missing logs
- **GIVEN** completed verified evidence lacks the selected executor or stream
- **WHEN** acquisition is requested
- **THEN** NOT_FOUND is returned without refreshing completed evidence or selecting another attempt

### Requirement: Enable gateway log access through explicit deployment configuration
Executor log acquisition SHALL be disabled when executor_log_node_manager_path is null; old Spark configurations SHALL remain valid. Enabled acquisition SHALL require a deployment-confirmed safe absolute NodeManager gateway path and a nonempty scheme/host/explicit-port upstream allowlist. Gateway root SHALL be derived from the configured HTTPS History Server /sparkhistory mount without a duplicated root setting. Rules SHALL use exact hosts or one DNS-label wildcard and MUST NOT include userinfo, paths, query strings, fragments or wildcard IP addresses. The two new fields SHALL use existing strict file/environment validation and precedence. Response and saved-text limits SHALL be fixed at 8 MiB and 1 MiB. Configuration validation MUST NOT contact upstreams or probe candidate routes.

#### Scenario: Enable one confirmed deployment route
- **GIVEN** same-root History configuration, one confirmed node manager path, and allowlisted NodeManager and JobHistory authorities
- **WHEN** valid file or equivalent environment-only configuration is loaded
- **THEN** executor-log acquisition is enabled with equivalent settings and no network request

#### Scenario: Reject foreign or incomplete gateway settings
- **GIVEN** an unsafe path, an empty allowlist for an enabled path, an unsafe wildcard or a History URL without the required gateway mount
- **WHEN** startup validates configuration
- **THEN** CONFIG_ERROR is returned without exposing credentials or making a request

### Requirement: Constrain gateway requests and identity-preserving redirects
Container-log requests SHALL target only the configured HTTPS gateway origin/root; embedded backend scheme/host/port SHALL match configured allowlist rules. Original NodeManager URLs SHALL be converted to the selected gateway route without a direct backend connection. The tool SHALL overwrite original start with negative tail_bytes, reject unknown or duplicate query parameters and end, and preserve validated container/owner/stream. It SHALL explicitly follow at most three 302/303/307/308 redirects, detect loops, and revalidate every next target before sending credentials or another request. Allowed destinations SHALL be the selected NodeManager log route and same-root JobHistory joblogs route. JobHistory NodeId SHALL be learned from Location, preserve the original NodeManager host and contain a valid port; entity SHALL equal container. Redirected JobHistory backend authority SHALL match the allowlist and remain fixed after first selection. SSO/login redirects SHALL return AUTHENTICATION_FAILED; foreign, identity-changing or unsupported redirects SHALL return UNEXPECTED_RESPONSE. Existing eventlog downloads MUST retain their no-redirect policy.

#### Scenario: Follow a completed container to aggregated logs
- **GIVEN** an allowlisted NodeManager URL and a same-root JobHistory Location with matching identity and approved history backend
- **WHEN** the log GET returns 307
- **THEN** the tool follows the validated gateway URL with bounded tail range, learns NodeId from Location and records JobHistory provenance in the manifest after valid publication

#### Scenario: Reject a backend query bypass
- **GIVEN** a same-origin URL whose scheme/host/port query points at an unapproved backend
- **WHEN** URL validation runs
- **THEN** UNEXPECTED_RESPONSE is returned before that request, even though the gateway origin matches

#### Scenario: Reject login, foreign origin and changed container
- **GIVEN** Location points to SSO, another origin, another container, another owner or another stream
- **WHEN** redirect handling validates Location
- **THEN** no next log request is made, credentials stay scoped, and SSO maps to AUTHENTICATION_FAILED while other violations map to UNEXPECTED_RESPONSE

#### Scenario: Stop a redirect loop or excessive chain
- **GIVEN** repeated targets or a fourth redirect
- **WHEN** the redirect policy runs
- **THEN** UNEXPECTED_RESPONSE is returned with no further request or published executor-log evidence

### Requirement: Keep authentication private throughout log acquisition
The tool SHALL reuse environment-supplied Cookie or existing paired Knox Basic credentials and same-origin SSO configuration. The log network segment SHALL perform at most one configured Basic login, with Authorization sent only to that SSO POST and cookies applied only to validated gateway destinations. An internal eventlog download SHALL retain its own existing authentication contract while consuming the same outer deadline. The tool MUST NOT extract browser credentials, follow SSO redirects, automatically refresh credentials, retry passwords, inherit ambient proxy/CA overrides or persist cookies. All configured secrets, Basic encoding and acquired cookie values SHALL enter redaction context; cookie jars and owned clients SHALL be cleared/closed on completion, failure, cancellation and shutdown. TLS defaults and explicit deployment overrides SHALL remain those of existing Spark configuration.

#### Scenario: Authenticate a redirected log GET
- **GIVEN** Basic mode produces applicable cookies and NodeManager redirects to valid same-gateway JobHistory
- **WHEN** acquisition proceeds
- **THEN** only the configured SSO POST carries Basic Authorization, log GETs use applicable cookies, and no credential appears in files/results/diagnostics

#### Scenario: Reject unsuccessful login without retry
- **GIVEN** configured login returns 401 or lacks a cookie applicable to the requested gateway log URL
- **WHEN** login validation runs
- **THEN** AUTHENTICATION_FAILED is returned without a log GET, password retry or retained cookie

### Requirement: Validate bounded HTML log content and expose honest coverage
The tool SHALL request one stdout/stderr tail, reject source text exceeding requested tail_bytes as UNEXPECTED_RESPONSE rather than infer source offsets from redacted sizes, enforce fixed actual cumulative 8 MiB response and 1 MiB output bounds, and accept only recognized UTF-8 NodeManager or aggregated-log HTML with request URL-bound container identity, matching stream metadata and one unambiguous content block. If the page supplies explicit identity metadata it SHALL match, but absent page identity metadata MUST NOT alone cause rejection. Template whitespace pre blocks SHALL NOT count as log versions, and container strings appearing only in log content MUST NOT serve as identity evidence. HTML/scripts/resources MUST NOT be executed. HTTP200 alone or an arbitrary pre block MUST NOT establish success. Login pages SHALL map to AUTHENTICATION_FAILED; ACL pages to PERMISSION_DENIED; explicit missing/aggregation-pending pages to NOT_FOUND; unknown encodings/shapes or multiple same-stream versions to UNEXPECTED_RESPONSE. It SHALL preserve decoded log text apart from mandatory redaction, conservative first-boundary-line discard when the source byte start is confirmed nonzero and bounded output trimming; an EOF-final line MUST NOT be discarded merely because it has no newline. Empty confirmed streams SHALL succeed. Source length and truncation SHALL be reported honestly as defined in design.md; unknown total length MUST NOT be invented.

#### Scenario: Extract a recognized aggregated stderr body
- **GIVEN** matching Log Type, container identity, length metadata and one content block
- **WHEN** HTML validation and extraction run
- **THEN** decoded log text is processed into local evidence, available source-size metadata is recorded in the manifest, and SparkExecutorLogFetchResult reports actual output size and coverage

#### Scenario: Reject HTML200 error and login pages
- **GIVEN** a login form, ACL denial or explicit unavailable-log page instead of valid log content
- **WHEN** the response is classified
- **THEN** the corresponding shared ToolError is returned and no executor-log evidence is published

#### Scenario: Preserve an empty stream or unknown coverage
- **GIVEN** a valid zero-length stream or a recognized log page without total-size metadata
- **WHEN** acquisition succeeds
- **THEN** a zero-byte stream is valid, absent source size is null in the manifest, and coverage is unknown unless tail omission or full coverage is established

#### Scenario: Reject response overflow and ambiguous versions
- **GIVEN** actual cumulative response bytes exceed the fixed bound or multiple content versions match the same stream
- **WHEN** the response is consumed and validated
- **THEN** overflow returns non-retryable UPSTREAM_ERROR, ambiguity returns UNEXPECTED_RESPONSE, and neither publishes partial evidence

### Requirement: Publish private redacted log evidence with provenance
Successful acquisition SHALL return the named SparkExecutorLogFetchResult with exactly application_id, attempt_id, executor_id, container_id, log_type, requested_tail_bytes, fetched_at, coverage, local_path, size_bytes, sha256 and manifest_path. Types, nullable fields and semantics SHALL follow design.md. Each call SHALL publish a fresh directory containing one UTF-8 stdout.log or stderr.log and one manifest.json; no executor-log cache hit or overwrite SHALL occur. The manifest SHALL bind the result to gateway source, route, redacted source URL and verified eventlog path/hash. Directories/files SHALL be private, paths SHALL reject symlinks and traversal, publication SHALL be atomic after validation/redaction/hash checks, and raw HTML/unredacted text SHALL never be persisted. Fixed credential patterns, configured secrets and acquired cookies SHALL be removed across chunk/line boundaries. Confirmed partial first lines SHALL be handled safely; EOF-final lines SHALL be preserved and redacted even without newline. Coverage SHALL reflect omissions, while detailed source/processing metadata SHALL stay in the manifest. Published results SHALL contain only paths and structural summaries, never raw log text or credentials.

#### Scenario: Publish one executor log and its manifest
- **GIVEN** valid bounded HTML log content and verified eventlog provenance
- **WHEN** credential redaction, private file writes and digest checks succeed
- **THEN** both files are atomically published and SparkExecutorLogFetchResult paths and hashes identify the saved redacted evidence

#### Scenario: Redact credentials and unsafe boundary fragments
- **GIVEN** logs contain secret values, multiline headers, split-buffer credentials or partial tail boundary lines
- **WHEN** text processing runs
- **THEN** protected values/fragments do not enter evidence/results/diagnostics, the first boundary line is omitted when the source byte start is confirmed nonzero, complete EOF-final lines are retained, and coverage records any omission

#### Scenario: Keep repeated requests fresh and prior evidence intact
- **GIVEN** earlier successfully published executor-log evidence exists
- **WHEN** the same request succeeds again or a later request fails
- **THEN** successful acquisition creates another directory, a failed acquisition removes only its unpublished staging, and earlier evidence remains intact

### Requirement: Share one deadline and preserve resource and stdio boundaries
The full operation SHALL consume one configured timeout covering queueing, eventlog lookup/download, log authentication/redirects/streaming, parsing/redaction and publication. It SHALL use the existing Spark process's exclusive cache_dir ownership without acquiring a competing lock. Timeout/cancellation/shutdown SHALL cancel and await owned work, close streams/files/clients, clear cookies and remove only unpublished executor-log staging; separately completed eventlog evidence SHALL remain usable. Errors SHALL use existing ToolError categories and new operation fetch_spark_executor_log with only validated application_id/attempt_id/executor_id/log_type identifiers. Raw bodies, headers, exception representations, logs and stack traces MUST NOT enter MCP output or ordinary diagnostics; stdout SHALL remain MCP JSON-RPC only. Services MUST remain independent of MCP and external clients, and no plugin-to-plugin calls SHALL be introduced.

#### Scenario: Exhaust the budget while resolving or following redirects
- **GIVEN** the original deadline expires during any acquisition phase
- **WHEN** cancellation and cleanup run
- **THEN** safe TIMEOUT is returned, no executor-log partial result is published, and owned resources are released without resetting the budget

#### Scenario: Close a process with an active executor log call
- **GIVEN** a Spark process holds its one evidence-directory lock and has an active log request
- **WHEN** MCP shutdown occurs
- **THEN** owned work ends and clients/staging are cleaned before the directory owner releases the lock for a later process

#### Scenario: Return safe errors and preserve plugin isolation
- **GIVEN** an upstream failure or malformed request occurs in the executor-log tool
- **WHEN** the stdio adapter responds
- **THEN** the error operation is fetch_spark_executor_log, only approved safe identifiers are included, stdout contains only protocol messages, and unrelated plugins remain unaffected

### Requirement: Verify one real stdout download before tool generalization
The first validation milestone SHALL reuse existing Spark authentication and text redaction to fetch the user-designated Driver stdout URL. It SHALL use an authorized private credential source, a bounded request and private local evidence; raw credentials/HTML/log text MUST NOT be printed or persisted. This operator validation URL MUST NOT become a public arbitrary-URL MCP argument. The milestone SHALL pass only after authentication, recognized stdout extraction, private publication, independent digest verification and configured/acquired secret absence have been observed against the real service. A mock, HTML200 login page or unavailable credential environment MUST NOT be reported as a successful live download. Public tool implementation SHALL remain a later task.

#### Scenario: Complete the real stdout milestone
- **GIVEN** the user's authorized stdout URL and usable existing Spark authentication context
- **WHEN** the bounded request returns recognized stdout and private redacted evidence is verified
- **THEN** verification.md records safe HTTP/identity/file/hash results and only the validation task is completed

#### Scenario: Keep a blocked live validation incomplete
- **GIVEN** no usable authentication context or no recognized stdout is available
- **WHEN** the live validation is attempted or its prerequisites are checked
- **THEN** the exact safe blocker is recorded and neither the milestone nor the public tool is claimed complete
