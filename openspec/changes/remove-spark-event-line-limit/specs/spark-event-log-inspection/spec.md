## ADDED Requirements

### Requirement: Read large records under the snapshot total budget
The verified offline reader used by inspection, query and metrics SHALL accept valid records larger than 8 MiB within configured max_bytes, without an independent record cap. Each read SHALL be bounded by the remaining selected-file byte budget plus one overflow-detection byte. Existing snapshot identity, hash, count, redaction, output text limits and total deadline SHALL remain enforced. Snapshot overflow SHALL return safe UNEXPECTED_RESPONSE without a partial successful result.

#### Scenario: Inspect and query a large event
- **GIVEN** a verified snapshot contains a valid event larger than 8 MiB while its total fits max_bytes
- **WHEN** it is inspected and the large event is queried by physical line
- **THEN** SparkEventLogInspectionResult contains full counts and SparkEventQueryResult preserves its digest/line reference with bounded details and truthful truncation

#### Scenario: Preserve offline size enforcement
- **GIVEN** a consistent snapshot's size exceeds max_bytes by one byte
- **WHEN** an offline reader scans it
- **THEN** safe UNEXPECTED_RESPONSE replaces the requested named result

#### Scenario: Accept EOF at the configured byte boundary
- **GIVEN** a valid selected snapshot is exactly max_bytes
- **WHEN** an offline reader verifies it
- **THEN** the named result is returned only after verified EOF with the existing hash and event count
