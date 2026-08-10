## ADDED Requirements

### Requirement: Expose the DolphinScheduler scheduling tools
The DolphinScheduler plugin SHALL expose exactly these six scheduling tools: `list_objects`, `get_object`, `search_objects`, `start_workflow`, `get_task_log`, and `extract_log_links`. The plugin MUST NOT expose tools that create, update, delete, stop, pause, resume, or force-succeed DolphinScheduler objects in V1.

#### Scenario: List the DolphinScheduler scheduling tools
- **WHEN** an MCP client lists tools for a DolphinScheduler plugin process
- **THEN** the scheduling tool set is exactly `list_objects`, `get_object`, `search_objects`, `start_workflow`, `get_task_log`, and `extract_log_links`

### Requirement: Validate DolphinScheduler scheduling object references
Every scheduling tool that addresses an object SHALL accept an `object_type` that is exactly one of `project`, `workflow`, `node`, `process_instance`, or `task_instance`. `project_code` SHALL be a 64-bit integer and SHALL be required for every type except `project`. Definitions (`project`, `workflow`, `node`) SHALL be addressed by a `code` (64-bit integer); instances (`process_instance`, `task_instance`) SHALL be addressed by an `id` (integer). Pagination inputs SHALL default to page 1 and `default_page_size`, and SHALL be capped at `max_page_size`. Search keywords SHALL be non-empty and bounded. Validation failures SHALL use fixed messages and MUST NOT echo rejected input beyond safe identifiers.

#### Scenario: Reject an unknown object type
- **WHEN** a scheduling tool receives an `object_type` that is not one of the five supported values
- **THEN** the tool returns `INVALID_INPUT` without making a network request

#### Scenario: Reject a missing project code
- **WHEN** a scheduling tool receives `object_type` `workflow` without a `project_code`
- **THEN** the tool returns `INVALID_INPUT` without making a network request

#### Scenario: Cap requested page size
- **WHEN** a scheduling tool receives a `page_size` greater than `max_page_size`
- **THEN** the tool uses `max_page_size` for the upstream request

### Requirement: Map DolphinScheduler scheduling failures to safe error categories
Every scheduling tool SHALL map failures to `CONNECTION_FAILED`, `TIMEOUT`, `AUTHENTICATION_FAILED`, `PERMISSION_DENIED`, `UPSTREAM_ERROR`, or `UNEXPECTED_RESPONSE` without returning a raw HTTP client exception, response headers, cookies, credentials, or an unbounded body. HTTP 401 SHALL map to `AUTHENTICATION_FAILED`, HTTP 403 to `PERMISSION_DENIED`, HTTP 5xx and 2xx responses with a non-zero DolphinScheduler `Result.code` to `UPSTREAM_ERROR`, and an unparseable `Result` envelope or unexpected `data` shape to `UNEXPECTED_RESPONSE`.

#### Scenario: Authentication is rejected
- **WHEN** a scheduling operation receives HTTP 401
- **THEN** the tool returns `AUTHENTICATION_FAILED`

#### Scenario: Business error on HTTP 200
- **WHEN** a scheduling operation receives HTTP 200 with a non-zero `Result.code`
- **THEN** the tool returns `UPSTREAM_ERROR` with a concise safe message

### Requirement: Bound and redact DolphinScheduler scheduling results
Every scheduling tool SHALL bound list and detail results by `max_detail_items`, bound log fetches by `max_log_bytes`, return only safe normalized fields, and MUST NOT return raw HTTP artifacts, response headers, cookies, credentials, the DolphinScheduler `msg` field on success, or an unbounded upstream body.

#### Scenario: Bound a large list
- **WHEN** a list or search result exceeds `max_detail_items`
- **THEN** the tool returns only the first `max_detail_items` summaries

#### Scenario: Drop unknown fields
- **WHEN** an upstream object contains fields outside the safe summary set
- **THEN** the tool omits them without failing

### Requirement: List DolphinScheduler scheduling objects
The `list_objects` tool SHALL enumerate objects of the requested `object_type` by calling the matching DolphinScheduler 3.1.7 list endpoint: `project` via `GET /projects/list`, `workflow` via `GET /projects/{projectCode}/process-definition/list`, `node` via `GET /projects/{projectCode}/task-definition`, `process_instance` via `GET /projects/{projectCode}/process-instances`, and `task_instance` via `GET /projects/{projectCode}/task-instances`. It SHALL accept optional `process_definition_code` to filter `process_instance` and optional `process_instance_id` to filter `task_instance`, and SHALL return the `object_type`, a bounded list of safe summaries, and pagination reflectors.

#### Scenario: List workflows in a project
- **WHEN** `list_objects` is called with `object_type` `workflow` and a valid `project_code`
- **THEN** the tool returns bounded workflow summaries from the process-definition list endpoint

#### Scenario: List task instances of a process instance
- **WHEN** `list_objects` is called with `object_type` `task_instance`, a `project_code`, and a `process_instance_id`
- **THEN** the tool returns bounded task-instance summaries filtered by that process instance

### Requirement: Get DolphinScheduler object attributes and instances
The `get_object` tool SHALL return the attributes of a specific object and, for definitions and process instances, its related instances. It SHALL call `GET /projects/{code}` for `project`, `GET /projects/{projectCode}/process-definition/{code}` for `workflow` and also return that workflow's process instances, `GET /projects/{projectCode}/task-definition/{code}` for `node`, `GET /projects/{projectCode}/process-instances/{id}` for `process_instance` and also return that instance's task instances, and for `task_instance` SHALL fetch `GET /projects/{projectCode}/process-instances/{process_instance_id}/tasks` and return the entry matching `task_instance_id` (requiring `process_instance_id`).

#### Scenario: Get a workflow and its instances
- **WHEN** `get_object` is called with `object_type` `workflow`, a `project_code`, and a `code`
- **THEN** the tool returns the workflow attributes and a bounded list of its process instances

#### Scenario: Get a process instance and its tasks
- **WHEN** `get_object` is called with `object_type` `process_instance`, a `project_code`, and an `id`
- **THEN** the tool returns the process-instance attributes and a bounded list of its task instances

#### Scenario: Resolve a task instance via its process instance
- **WHEN** `get_object` is called with `object_type` `task_instance`, a `project_code`, a `process_instance_id`, and a `task_instance_id`
- **THEN** the tool returns the matching task-instance attributes from the process instance task list

### Requirement: Search DolphinScheduler scheduling objects
The `search_objects` tool SHALL perform keyword search across object types by applying the search keyword to the matching DolphinScheduler parameter: `searchVal` for `project`, `workflow`, `process_instance`, and `task_instance`, and `searchTaskName` for `node`. For instances it SHALL accept optional `state_type`, `start_date`, and `end_date` filters. It SHALL return the `object_type`, bounded matching summaries, and pagination reflectors.

#### Scenario: Search process instances by keyword
- **WHEN** `search_objects` is called with `object_type` `process_instance`, a `project_code`, and a `search_val`
- **THEN** the tool returns bounded matching process-instance summaries

#### Scenario: Search nodes by task name
- **WHEN** `search_objects` is called with `object_type` `node`, a `project_code`, and a `search_val`
- **THEN** the tool applies the keyword as `searchTaskName` and returns bounded matching node summaries

### Requirement: Start a DolphinScheduler workflow
The `start_workflow` tool SHALL start a process instance from a process definition by calling `POST /projects/{projectCode}/executors/start-process-instance` with `processDefinitionCode` and safe defaults: `failureStrategy` `CONTINUE`, `warningType` `NONE`, `dryRun` `0`, `workerGroup` `default`, and an empty `scheduleTime`. It SHALL accept optional bounded `start_node_list` and `timeout`, and an explicit `dry_run` flag. It SHALL return the process definition code, the returned process instance id when present, the dry-run flag, and a safe message. It MUST NOT retry execution automatically.

#### Scenario: Start a workflow
- **WHEN** `start_workflow` is called with a `project_code` and `process_definition_code` and the upstream accepts the request
- **THEN** the tool returns the process definition code, the process instance id when present, and a safe acknowledgement

#### Scenario: Dry-run a workflow
- **WHEN** `start_workflow` is called with `dry_run` enabled
- **THEN** the tool requests a DolphinScheduler dry run that validates without executing

### Requirement: Get a DolphinScheduler task execution log
The `get_task_log` tool SHALL read a task instance's bounded execution log by calling `GET /log/{projectCode}/detail` with `taskInstanceId`, `skipLineNum`, and `limit`. It SHALL default `skip_line_num` to 0, cap `limit`, and return `task_instance_id`, `line_num` (the next read offset), the bounded log `message`, and a `truncated` flag. It MUST NOT return an unbounded body.

#### Scenario: Read the first page of a task log
- **WHEN** `get_task_log` is called with a `project_code` and `task_instance_id`
- **THEN** the tool returns the bounded log text starting at line 0 and the next offset

#### Scenario: Continue reading a task log
- **WHEN** `get_task_log` is called with a `skip_line_num` equal to a previous `line_num`
- **THEN** the tool returns the next bounded page of log text

### Requirement: Extract YARN and Spark links from a DolphinScheduler task log
The `extract_log_links` tool SHALL fetch a task instance's full log via `GET /log/{projectCode}/download-log` bounded by `max_log_bytes`, then extract YARN application IDs matching `application_\d+_\d+` and Spark UI / tracking URLs matching `http(s)://<host>/proxy/application_\d+_\d+` or `Spark UI:`-prefixed URLs. It SHALL return deduplicated, bounded `yarn_application_ids` and `spark_ui_urls`, and MUST NOT return raw log text.

#### Scenario: Extract links from a shell node log
- **WHEN** `extract_log_links` is called for a task instance whose log contains a YARN application ID and a Spark tracking URL
- **THEN** the tool returns the application ID and the tracking URL in the respective lists without returning the log text

#### Scenario: No links present
- **WHEN** the fetched log contains no matching YARN or Spark link
- **THEN** the tool returns empty `yarn_application_ids` and `spark_ui_urls` lists
