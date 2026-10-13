## Purpose

Provide a small Spark History Server download tool that converts a YARN application identifier into validated, credential-safe local JSONL files and one manifest. Allow subsequent diagnostic sessions to reuse these files directly without building a general cache or snapshot storage system.

## ADDED Requirements

### Requirement: Expose one event log download tool
The Spark plugin SHALL expose exactly `fetch_spark_event_log(application_id: string, attempt_id: string | null = null, refresh: bool = false)`. Application identifiers SHALL match ASCII `application_[0-9]+_[0-9]+` with at most 128 characters; non-null attempts SHALL match `[A-Za-z0-9_-]{1,128}`. The tool MUST NOT accept arbitrary URLs, output paths, credentials, headers or TLS overrides. It SHALL return the named `SparkEventLogFetchResult` containing application_id, requested_attempt_id, cache_hit, downloaded_at, manifest_path and an array of named `SparkEventLogFile` values, with exactly the fields defined in design.md. Results MUST NOT contain raw events or credentials.

#### Scenario: Download one attempt
- **GIVEN** valid configuration and an application/attempt request
- **WHEN** its log is downloaded and saved successfully
- **THEN** SparkEventLogFetchResult contains one matching SparkEventLogFile and usable JSONL/manifest paths

#### Scenario: Download using only application ID
- **GIVEN** the History Server provides one or more attempt logs
- **WHEN** attempt_id is omitted
- **THEN** the all-attempts endpoint is used and each member is saved separately without selecting latest; a client-mode log may have null attempt_id

#### Scenario: Reject invalid input
- **GIVEN** a malformed identity, non-boolean refresh or unsupported caller argument
- **WHEN** schema/service validation runs
- **THEN** it rejects the request before network/file mutation, using shared ToolError category INVALID_INPUT for application-level failures

### Requirement: Download only from the configured trusted HTTPS endpoint
The tool SHALL use only the documented Spark History Server GET paths in design.md, preserving the configured mount. Existing optional gateway Cookie credentials SHALL come from environment variables. TLS verification SHALL default to enabled with default trust or a configured trusted CA. Deployment settings MAY explicitly set strict boolean verify_tls=false (SPARK_VERIFY_TLS=false) to disable certificate and hostname verification; this MUST NOT be a tool argument. A configured CA file SHALL still be locally validated but SHALL NOT be used for connections when verification is disabled. The client MUST NOT follow redirects, inherit ambient proxy/CA overrides, extract browser credentials, perform unconfigured login, automatically refresh credentials or retry. For the download GET, HTTP 200 HTML login responses, 401 and redirects SHALL map to AUTHENTICATION_FAILED without exposing bodies or headers.

#### Scenario: Use the gateway mount and environment Cookie
- **GIVEN** a configured HTTPS gateway prefix and an environment-provided Cookie
- **WHEN** the tool downloads an attempt
- **THEN** one GET uses that prefix and the documented logs path, and credentials stay scoped to the configured origin

#### Scenario: Detect unauthenticated downloads
- **GIVEN** a redirect, HTTP 401 or HTTP 200 HTML login page
- **WHEN** the response is inspected
- **THEN** shared ToolError reports AUTHENTICATION_FAILED, no redirect is followed and no evidence is published

#### Scenario: Require a trusted certificate
- **GIVEN** a private server certificate and default verify_tls=true
- **WHEN** a valid trusted CA is supplied
- **THEN** verification remains enabled; without trust the tool reports CONNECTION_FAILED instead of bypassing verification

#### Scenario: Explicitly skip certificate verification
- **GIVEN** deployment configuration explicitly sets verify_tls=false
- **WHEN** the client connects to the configured HTTPS endpoint
- **THEN** certificate and hostname checks are disabled while fixed origin, redirect rejection, Cookie handling and response validation remain enforced

### Requirement: Bound and validate ZIP and JSONL input
The tool SHALL enforce configured max_bytes independently on actual ZIP bytes, total expanded source bytes and total saved JSONL bytes, and one overall deadline covering queueing, lookup and download/processing. It SHALL use public standard-library ZipFile APIs and fixed limits of 16 members and 8 MiB per input/output record. It MUST validate CRC and reject encrypted/unsupported ZIP methods, non-regular members, symlinks, nested/absolute/traversal paths and duplicate names/attempts. Member contents SHALL be uncompressed UTF-8 JSONL objects with valid Event discriminators, consistent LogStart and ApplicationStart records, and application/attempt/filename identities matching the request. The observed Spark Version SHALL be recorded without a patch-version allowlist. No compressed or rolling event-log format SHALL be supported in version one.

#### Scenario: Validate the observed Spark distribution
- **GIVEN** a valid single-file log from Spark 2.4.7.7.1.7.1000-141
- **WHEN** CRC, identities, JSON records and byte limits pass
- **THEN** SparkEventLogFile records the observed version, source/output digests, output size and event count

#### Scenario: Reject invalid archives or identities
- **GIVEN** a corrupt CRC, unsafe ZIP member, excessive bytes or conflicting application/attempt
- **WHEN** validation runs
- **THEN** the tool stops with the safe error mapping in design.md and publishes none of that download

#### Scenario: Reject malformed records without repair
- **GIVEN** invalid UTF-8, non-object JSON, a missing Event, malformed JSON or an incomplete final record
- **WHEN** the member is read, including an .inprogress member
- **THEN** UNEXPECTED_RESPONSE is returned without tail repair or partial publication

#### Scenario: Preserve valid logs without ApplicationEnd
- **GIVEN** all records and identities are valid but ApplicationEnd is absent
- **WHEN** the file is saved
- **THEN** SparkEventLogFile.application_end_seen is false, without deriving YARN or SQL success/failure/running state

### Requirement: Persist credential-safe files and one manifest
Each successful download SHALL save generated JSONL files and exactly one manifest.json in one private download directory. The tool SHALL apply the fixed credential redaction and EnvironmentUpdate allowlist defined in design.md while preserving event order, structure and numeric metrics. Source and output SHA-256 values MUST be distinguished. The manifest SHALL contain format_version=1, the configured source URL and all SparkEventLogFetchResult fields except cache_hit. Raw ZIP and unsanitized JSON SHALL be temporary only. All selected members MUST validate before publishing the directory with a same-filesystem rename. Existing successful directories MUST NOT be overwritten or removed by a failed or refreshed download.

#### Scenario: Generate local evidence during acquisition
- **GIVEN** a downloaded ZIP passes validation
- **WHEN** its events are parsed and redacted in a private temporary directory
- **THEN** JSONL is generated there, the raw ZIP is removed, and the completed JSONL/manifest directory is published before returning SparkEventLogFetchResult

#### Scenario: Remove embedded credentials
- **GIVEN** source events contain credential fields, assignments, URLs or configured Cookie values
- **WHEN** the fixed redaction policy runs
- **THEN** those values are absent from persisted files, results and logs while safe event structure/order and metrics remain

#### Scenario: Discard a failed multi-member download
- **GIVEN** an earlier member validates but a later member fails or the request is cancelled
- **WHEN** processing stops
- **THEN** the tool deletes its unpublished temporary directory and preserves all previous successful directories

### Requirement: Reuse local evidence with explicit refresh
With refresh=false the tool SHALL reuse the newest structurally valid manifest matching configured source URL, application_id and requested_attempt_id, after checking local file paths and hashes. It SHALL return cache_hit=true and the original downloaded_at without connecting upstream. With no candidate, or with refresh=true, it SHALL download once and return cache_hit=false. A corrupt matching candidate SHALL return UNEXPECTED_RESPONSE instead of silently serving it. All-attempts and selected-attempt requests MUST match exactly. Files SHALL persist until user-managed cleanup; version one SHALL NOT implement TTL, deduplication, content-addressed storage, reference counting, automatic GC, global quotas or a separate offline policy.

#### Scenario: Reuse across diagnostic sessions
- **GIVEN** a previous Spark process saved evidence and exited
- **WHEN** a later process requests the same source and exact selection with refresh=false
- **THEN** verified local SparkEventLogFetchResult is returned with no network request and the original download time

#### Scenario: Refresh without overwriting evidence
- **GIVEN** a matching download directory already exists
- **WHEN** refresh=true succeeds
- **THEN** a new directory is saved even for identical content, and the previous directory remains available

#### Scenario: Exclude mismatched or damaged evidence
- **GIVEN** a candidate has a different source/selection, or a matching candidate has missing/changed files
- **WHEN** lookup runs
- **THEN** the mismatched candidate is not reused and a damaged matching candidate returns UNEXPECTED_RESPONSE; refresh=true allows a new acquisition

### Requirement: Keep local ownership and lifecycle simple
The plugin SHALL use a dedicated private cache_dir with directory/file permissions 0700/0600 and a standard POSIX exclusive non-blocking root lock. A second live process using the same root SHALL fail with CONFIG_ERROR locally. Sequential processes MAY reuse persisted evidence after the prior owner exits. Startup SHALL validate configuration and acquire the local lock without network access. Acquisitions SHALL be serialized within the total deadline. Owned HTTP/file resources SHALL close on failure, cancellation, timeout and shutdown; unpublished work created by the call SHALL be removed. Abrupt-kill temporary remnants MUST NOT be cache candidates and MAY be manually cleaned; no crash-recovery manager is required.

#### Scenario: Prevent concurrent cache ownership
- **GIVEN** an active Spark process holds the configured directory lock
- **WHEN** another process starts with the same cache_dir
- **THEN** startup fails with CONFIG_ERROR without contacting upstream or altering saved files

#### Scenario: Close a timed-out acquisition
- **GIVEN** the total deadline expires during transfer or processing
- **WHEN** cleanup executes
- **THEN** TIMEOUT is returned, owned handles close and unpublished files are removed while saved evidence remains

### Requirement: Preserve shared errors and MCP stdio boundaries
Failures SHALL use the shared ToolError fields/categories and operation fetch_spark_event_log, with only validated application_id/attempt_id identifiers. The mappings SHALL follow design.md. Raw exceptions, response bodies, headers, cookies, event text and stack traces MUST NOT appear in output or ordinary logs. Wire logging MUST be suppressed before creating the HTTP client; stdout SHALL contain only MCP protocol messages.

#### Scenario: Report a missing application safely
- **GIVEN** History Server responds HTTP 404
- **WHEN** the adapter maps the failure
- **THEN** shared ToolError contains NOT_FOUND, safe identifiers, retryable=false and a correlation ID without the body

#### Scenario: Expose only the Spark tool over stdio
- **GIVEN** a locally configured Spark process
- **WHEN** tools are listed and success/cache/error calls are made
- **THEN** only fetch_spark_event_log is exposed and stdout remains protocol-only with redacted stderr diagnostics


### Requirement: Authenticate through configured Knox Basic login
The plugin SHALL support optional paired environment secrets username/password and a same-origin HTTPS knox_sso_url, mutually exclusive with gateway_cookie. Invalid combinations SHALL fail locally with CONFIG_ERROR. Before each actual download it SHALL POST an empty body to the configured SSO endpoint, passing encoded originalUrl and HTTP Basic credentials, and use only applicable response cookies for the download GET. Basic Authorization MUST NOT reach download or redirected endpoints. Login and download SHALL share the deadline and TLS settings; no redirects, retries, or persistent cookie storage are allowed. Login status/cookie checks and safe errors SHALL follow design.md; a valid event-log archive is required for final success. Response cookies SHALL be cleared on all receive exits; credential and acquired cookie values SHALL be excluded from saved evidence, results and diagnostics.

#### Scenario: Exchange Basic credentials and download
- **GIVEN** valid paired credentials and same-origin SSO configuration
- **WHEN** a network download is needed
- **THEN** one Basic-authenticated POST obtains cookies, followed by one cookie-authenticated GET without Basic Authorization, producing SparkEventLogFetchResult only after archive validation

#### Scenario: Reject invalid authentication configuration locally
- **GIVEN** partial credentials, both authentication modes, missing SSO endpoint or a foreign-origin endpoint
- **WHEN** plugin startup validates configuration
- **THEN** CONFIG_ERROR occurs without network access or leaked credentials

#### Scenario: Reject unsuccessful login without retry
- **GIVEN** login returns 401, or lacks a cookie applicable to the download URL
- **WHEN** login validation runs
- **THEN** AUTHENTICATION_FAILED is returned, no download or redirect occurs and temporary cookies are cleared

#### Scenario: Keep acquired credentials out of evidence
- **GIVEN** event text contains the configured password, Basic encoding or acquired cookie values
- **WHEN** downloaded events are processed
- **THEN** saved JSONL, manifest and SparkEventLogFetchResult omit those values

#### Scenario: Cache reuse avoids authentication
- **GIVEN** matching valid local evidence and Basic credentials
- **WHEN** refresh=false produces a cache hit
- **THEN** SparkEventLogFetchResult is returned without login or download requests
