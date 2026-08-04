## MODIFIED Requirements

### Requirement: Return safe stable tool errors
The system SHALL map plugin failures to `CONFIG_ERROR`, `INVALID_INPUT`, `AUTHENTICATION_FAILED`, `PERMISSION_DENIED`, `NOT_FOUND`, `CONNECTION_FAILED`, `TIMEOUT`, `UPSTREAM_ERROR`, or `UNEXPECTED_RESPONSE` before returning an MCP tool error. A tool error MAY include a concise `explanation` naming the rejection cause with safe identifiers; the `explanation` MUST NOT contain credentials, stack traces, raw upstream bodies, or rejected input beyond safe identifiers. The stable per-category `message` SHALL remain fixed regardless of the `explanation`.

#### Scenario: Return an expected upstream failure
- **WHEN** an upstream service rejects authentication or reports a known error
- **THEN** the tool error contains a stable category, operation, safe identifiers, concise message, retryability, and an optional concise explanation without raw upstream objects or credentials

#### Scenario: Return a rejection with a specific explanation
- **WHEN** a plugin rejects input for a specific configurable rule such as an allowlist or blacklist
- **THEN** the tool error includes a concise explanation naming the rule and the safe identifier that caused the rejection, without credentials or raw input bodies

#### Scenario: Return an unexpected exception
- **WHEN** an uncategorized exception reaches the MCP boundary
- **THEN** the client receives a generic safe error and stderr contains a correlation ID for diagnosis
