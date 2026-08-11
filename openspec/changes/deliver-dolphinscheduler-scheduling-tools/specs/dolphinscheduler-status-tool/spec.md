## MODIFIED Requirements

### Requirement: Expose only the DolphinScheduler server-status tool
The DolphinScheduler plugin SHALL expose the `get_server_status` tool defined by this capability. Enumeration, retrieval, search, execution, task-log, and log-link operations for projects, workflows, nodes, and their instances are defined by the `dolphinscheduler-scheduling-tools` capability and are no longer prohibited.

#### Scenario: List DolphinScheduler tools
- **WHEN** an MCP client lists tools for a DolphinScheduler plugin process
- **THEN** the returned tool set includes `get_server_status` plus the six `dolphinscheduler-scheduling-tools` tools

### Requirement: Validate a fixed DolphinScheduler V1 configuration
The DolphinScheduler plugin SHALL accept only these non-sensitive settings: `base_url`, `status_path`, `request_timeout_seconds`, `max_response_bytes`, `max_detail_items`, `default_page_size`, `max_page_size`, and `max_log_bytes`. `base_url` MUST be an absolute HTTP or HTTPS URL without user information, query, or fragment and SHALL be normalized without a trailing slash; it MAY include the DolphinScheduler `/dolphinscheduler` context path. `status_path` MUST start with a single `/`, MUST NOT contain a query or fragment, and SHALL default to `/monitor/masters`. Numeric settings SHALL use strict numeric types and the following inclusive ranges and defaults: timeout greater than zero and at most 300 seconds (default 30), response bytes 1 through 8 MiB (default 1 MiB), detail items 1 through 1,000 (default 100), default page size 1 through 100 (default 10), max page size 1 through 200 (default 100), and log bytes 1 through 8 MiB (default 1 MiB). The configuration SHALL reject unknown fields and coercion from strings, booleans, or other incompatible scalar types.

#### Scenario: Load equivalent DolphinScheduler settings
- **WHEN** equivalent valid settings are supplied in version 1 YAML and JSON files
- **THEN** they produce equivalent validated settings without making a network request

#### Scenario: Apply scheduling defaults
- **WHEN** `default_page_size`, `max_page_size`, and `max_log_bytes` are omitted
- **THEN** the validated values are 10, 100, and 1 MiB respectively

#### Scenario: Reject unsafe configuration
- **WHEN** `base_url` contains credentials, query, or fragment, `status_path` does not start with `/` or contains a query or fragment, a limit is outside its approved range, or an unknown field is present
- **THEN** startup fails with a safe `CONFIG_ERROR` that does not echo any secret value
