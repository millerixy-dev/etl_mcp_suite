## ADDED Requirements

### Requirement: Use aggregate budgets for event records
Acquisition SHALL accept otherwise valid JSONL records larger than 8 MiB when aggregate expanded source bytes and sanitized output bytes each fit configured max_bytes. There SHALL be no independent per-record byte cap. Reads SHALL be bounded by the remaining aggregate source budget plus one overflow-detection byte, with overflow rejected before parsing. ZIP byte limits, member count, CRC, identity, redaction, cleanup and total deadline contracts SHALL remain unchanged.

#### Scenario: Acquire a large event within budget
- **GIVEN** a valid archive containing an event larger than 8 MiB and aggregate source and output totals at or below max_bytes
- **WHEN** acquisition validates and redacts the archive
- **THEN** SparkEventLogFetchResult identifies complete JSONL with unchanged event order/count and correct source/output digests

#### Scenario: Reject aggregate overflow including redaction growth
- **GIVEN** source totals across members or sanitized output totals exceed max_bytes, including by one byte
- **WHEN** acquisition processes the archive
- **THEN** it returns safe UPSTREAM_ERROR and publishes no SparkEventLogFetchResult

#### Scenario: Accept exact source and output boundaries
- **GIVEN** valid source and sanitized output each fit max_bytes exactly, with or without a final source newline where output still fits
- **WHEN** acquisition reaches EOF
- **THEN** it returns SparkEventLogFetchResult without treating EOF as overflow
