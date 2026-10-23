## ADDED Requirements

### Requirement: Secret interpretation preserves source semantics
Spark SHALL treat usernames, passwords, Basic authorization encodings, and acquired individual Cookie values as opaque complete secrets. Only explicitly configured Cookie headers SHALL be split into cookie-pairs; the header and each complete nonempty value SHALL remain redaction targets. Secret normalization SHALL be idempotent and SHALL NOT infer secret fragments from delimiters or Base64 padding.

#### Scenario: Basic padding does not corrupt evidence
- **GIVEN** synthetic Basic credentials whose encoding ends in `==` and an event containing a Driver Logs URL with `?start=-4096`
- **WHEN** an event archive is downloaded and its Driver log is fetched
- **THEN** the SparkEventLogFetchResult evidence preserves the URL query and non-sensitive SQL equality expressions
- **AND** the SparkExecutorLogFetchResult references successfully acquired redacted text
- **AND** configured credentials and acquired cookies are absent from published text

#### Scenario: Cookie headers and individual values remain distinct
- **GIVEN** a configured Cookie header with multiple pairs and quoted padded values, or an acquired opaque value containing `=`
- **WHEN** secrets are prepared repeatedly for redaction
- **THEN** complete credential values remain redacted and no padding or value suffix is promoted to an independent secret

#### Scenario: Actual short secrets remain protected
- **GIVEN** an explicitly configured password equal to `=`
- **WHEN** text is redacted
- **THEN** the complete configured password is still removed, without a minimum-secret-length exemption

### Requirement: Published evidence remains immutable after redaction fixes
Spark SHALL preserve existing published evidence. Operators SHALL explicitly refresh event logs after this fix to obtain corrected evidence; tools SHALL NOT guess how to reverse prior redaction or relax malformed URL validation.

#### Scenario: Refresh replaces the usable snapshot
- **GIVEN** an older snapshot containing an over-redacted URL
- **WHEN** fetch_spark_event_log is called with refresh enabled
- **THEN** a new SparkEventLogFetchResult identifies fresh evidence while the old snapshot remains unchanged
