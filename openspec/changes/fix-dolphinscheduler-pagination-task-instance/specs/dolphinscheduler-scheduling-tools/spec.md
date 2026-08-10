## MODIFIED Requirements

### Requirement: List DolphinScheduler scheduling objects
The `list_objects` tool SHALL enumerate objects of the requested `object_type` by calling the matching DolphinScheduler 3.1.7 list endpoint: `project` via `GET /projects/list`, `workflow` via `GET /projects/{projectCode}/process-definition/list`, `node` via `GET /projects/{projectCode}/task-definition`, `process_instance` via `GET /projects/{projectCode}/process-instances`, and `task_instance` via `GET /projects/{projectCode}/task-instances`. It SHALL accept optional `process_definition_code` to filter `process_instance` and optional `process_instance_id` to filter `task_instance`, and SHALL return the `object_type`, a bounded list of safe summaries, and pagination reflectors.

For an upstream endpoint that returns an unpaginated collection, the tool SHALL apply the validated, capped 1-based `page_no` and `page_size` locally before returning summaries. It SHALL report the complete upstream collection size as `total_count`; return only entries in the requested page subject to `max_detail_items`; and set `truncated` only when `max_detail_items` removes entries from the requested page. A page beyond the available collection SHALL return an empty `items` array with the true `total_count`.

#### Scenario: List workflows in a project
- **WHEN** `list_objects` is called with `object_type` `workflow` and a valid `project_code`
- **THEN** the tool returns bounded workflow summaries from the process-definition list endpoint

#### Scenario: List task instances of a process instance
- **WHEN** `list_objects` is called with `object_type` `task_instance`, a `project_code`, and a `process_instance_id`
- **THEN** the tool returns bounded task-instance summaries filtered by that process instance

#### Scenario: Paginate an unpaginated project result
- **WHEN** the project endpoint returns four safe project entries and `list_objects` receives `object_type` `project`, `page_no` `2`, and `page_size` `3`
- **THEN** the tool returns only the fourth summary, reports `page_no` `2`, `page_size` `3`, `total_count` `4`, and `truncated` `false`

#### Scenario: Request an unpaginated page beyond the collection
- **WHEN** the project endpoint returns four safe project entries and `list_objects` receives `object_type` `project`, `page_no` `3`, and `page_size` `3`
- **THEN** the tool returns an empty `items` array with `total_count` `4` and `truncated` `false`

#### Scenario: Bound one locally selected page
- **WHEN** the selected unpaginated page contains more entries than `max_detail_items`
- **THEN** the tool returns only `max_detail_items` safe summaries and sets `truncated` to `true`

### Requirement: Get DolphinScheduler object attributes and instances
The `get_object` tool SHALL return the attributes of a specific object and, for definitions and process instances, its related instances. It SHALL call `GET /projects/{code}` for `project`, `GET /projects/{projectCode}/process-definition/{code}` for `workflow` and also return that workflow's process instances, `GET /projects/{projectCode}/task-definition/{code}` for `node`, `GET /projects/{projectCode}/process-instances/{id}` for `process_instance` and also return that instance's task instances, and for `task_instance` SHALL fetch `GET /projects/{projectCode}/process-instances/{process_instance_id}/tasks` and return the entry matching `task_instance_id` (requiring `process_instance_id`).

For the task-instance route, the adapter SHALL accept a successful DolphinScheduler 3.1.7 `Result` envelope only when its `data` is an object containing a `taskList` array. It SHALL ignore `processInstanceState` and all unknown fields, map each element only through the existing safe task-instance field whitelist, and reject a missing or non-array `taskList` as `UNEXPECTED_RESPONSE`. This compatibility requirement does not relax validation for any other endpoint.

#### Scenario: Get a workflow and its instances
- **WHEN** `get_object` is called with `object_type` `workflow`, a `project_code`, and a `code`
- **THEN** the tool returns the workflow attributes and a bounded list of its process instances

#### Scenario: Get a process instance and its tasks
- **WHEN** `get_object` is called with `object_type` `process_instance`, a `project_code`, and an `id`
- **THEN** the tool returns the process-instance attributes and a bounded list of its task instances

#### Scenario: Resolve a task instance via its process instance
- **WHEN** `get_object` is called with `object_type` `task_instance`, a `project_code`, a `process_instance_id`, and a `task_instance_id`
- **THEN** the tool returns the matching task-instance attributes from the process instance task list

#### Scenario: Resolve a task instance from the DolphinScheduler 3.1.7 wrapper
- **WHEN** the task-list endpoint returns a successful envelope whose `data` object contains a `taskList` array with the requested task instance and a `processInstanceState` field
- **THEN** `get_object` returns the requested normalized task-instance attributes and does not expose `processInstanceState` or unknown upstream fields

#### Scenario: Reject an invalid task-list wrapper
- **WHEN** the task-list endpoint returns a successful envelope whose `data` lacks `taskList` or has a non-array `taskList`
- **THEN** the tool returns `UNEXPECTED_RESPONSE` without returning raw upstream data
