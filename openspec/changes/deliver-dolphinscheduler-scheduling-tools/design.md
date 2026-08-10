## Context

The `deliver-dolphinscheduler-plugin-slice` change delivers the DolphinScheduler status tool plus the plugin scaffolding: configuration (`DolphinSchedulerSettings`, `DolphinSchedulerSecrets`), gateway port, asynchronous httpx adapter, application service, tool adapter, and composition root, all behind the shared core. A direct user requirement now expands the DolphinScheduler surface from observational status-only to a full scheduling toolset: enumerate projects, workflows, nodes, and their instances; inspect attributes; search; start a workflow; read a shell node's execution log; and extract YARN application IDs and Spark UI links from that log. This overrides the parent `build-plugin-mcp-stdio` design and `AGENTS.md`, which scoped DolphinScheduler as observational in V1.

All API facts below were verified against the Apache DolphinScheduler 3.1.7 source (tag `3.1.7`): controllers, DAO entities, and enums. They are consistent with the official 3.1.7 API documentation at https://dolphinscheduler.apache.org/en-us/docs/3.1.7.

## Goals / Non-Goals

**Goals:**

- Deliver six contract-tested scheduling tools that map to the verified DolphinScheduler 3.1.7 REST API.
- Reuse the status slice's gateway, httpx adapter, error mapping, and composition root without duplicating infrastructure.
- Bound every list, detail, and log result and redact all secrets, headers, cookies, and unbounded upstream bodies.
- Start workflows with safe execution defaults and an explicit dry-run option.
- Extract YARN application IDs and Spark UI / tracking URLs from a shell node's log with deterministic parsing.

**Non-Goals:**

- Creating, updating, or deleting DolphinScheduler objects (projects, workflows, nodes, schedules).
- Stopping, pausing, resuming, or force-succeeding process or task instances.
- Real-time log tailing or long-polling inside one tool call.
- Token refresh, session-cookie login, or LDAP.
- A generic SQL or REST passthrough.

## Decisions

### 1. Extend the status slice, not a new plugin

The six tools are added to the existing `dolphinscheduler` plugin built by `deliver-dolphinscheduler-plugin-slice`. The gateway gains scheduling methods, the service gains scheduling operations, and the tool adapter registers the six additional tools. No new package, dependency, or process is introduced. This mirrors how later Zeppelin changes extended `deliver-zeppelin-plugin-slice`.

### 2. Configuration expansion

This change adds three scheduling settings to `DolphinSchedulerSettings`, which is defined by `deliver-dolphinscheduler-plugin-slice`. The loader (`load_config` with `env_prefix="DOLPHINSCHEDULER"`), the base settings (`base_url`, `status_path`, `request_timeout_seconds`, `max_response_bytes`, `max_detail_items`), the `DolphinSchedulerSecrets.token` field, the file-vs-env precedence, local validation-without-network, and the `mcp-stdio` start command are all unchanged; see the slice's Section 2 for their field tables, secrets handling, and the base file/env examples. Only the three settings below are new; the complete allowed-settings closure is specified in the `dolphinscheduler-status-tool` capability (MODIFIED "Validate a fixed DolphinScheduler V1 configuration" requirement).

#### Scheduling settings (non-sensitive)

| Field | Type | Default | Range | Required |
|---|---|---|---|---|
| `default_page_size` | int | `10` | `1` to `100` | no |
| `max_page_size` | int | `100` | `1` to `200` | no |
| `max_log_bytes` | int | `1048576` (1 MiB) | `1` to `8388608` (8 MiB) | no |

`max_detail_items` (from the status slice) bounds every returned list and detail. Pagination inputs are capped at `max_page_size` and default to `default_page_size`. Log fetches (`get_task_log` and `extract_log_links`) are bounded by `max_log_bytes`. A `default_page_size` greater than `max_page_size` is accepted at load time; runtime pagination always caps a requested `page_size` at `max_page_size`.

#### File example (delta to `docs/examples/dolphinscheduler.yaml`)

Add the three keys to the existing `settings` block from the slice's example (base settings and `secrets.token` are unchanged):

```yaml
settings:
  default_page_size: 10                # optional, scheduling list/search page size
  max_page_size: 100                   # optional, hard cap for page_size inputs
  max_log_bytes: 1048576               # optional, bounds task-log fetches
```

The `mcp-stdio --plugin dolphinscheduler --config /path/to/dolphinscheduler.yaml` start command is unchanged.

#### Environment-variable-only example (delta)

Set the three `DOLPHINSCHEDULER_<FIELD>` variables (the base variables and `DOLPHINSCHEDULER_TOKEN` are documented in the slice's Section 2):

| Field | Variable | Required |
|---|---|---|
| `settings.default_page_size` | `DOLPHINSCHEDULER_DEFAULT_PAGE_SIZE` | no |
| `settings.max_page_size` | `DOLPHINSCHEDULER_MAX_PAGE_SIZE` | no |
| `settings.max_log_bytes` | `DOLPHINSCHEDULER_MAX_LOG_BYTES` | no |

```bash
export DOLPHINSCHEDULER_DEFAULT_PAGE_SIZE=20
export DOLPHINSCHEDULER_MAX_PAGE_SIZE=200
export DOLPHINSCHEDULER_MAX_LOG_BYTES=2097152
```

### 3. DolphinScheduler 3.1.7 API facts

Context path `/dolphinscheduler` (default API port 12345). Authentication via the `token` HTTP header (`LoginHandlerInterceptor.preHandle` reads `request.getHeader("token")`); a missing, invalid, or expired token returns HTTP 401 with no body. Every endpoint returns the `Result` envelope `{ "code": <int>, "msg": "<string>", "data": <T> }` where `code == 0` is `Status.SUCCESS`. Business errors return HTTP 200 with a non-zero `code` (for example `LIST_MASTERS_ERROR(10045)`).

Endpoint table (all require authentication; `pc` = `projectCode` path segment):

| Tool | Operation | Method | Path | Key query/form params |
|---|---|---|---|---|
| list project | queryAllProjectList | GET | `/projects/list` | - |
| search project | queryProjectListPaging | GET | `/projects` | `searchVal`, `pageNo`, `pageSize` |
| get project | queryProjectByCode | GET | `/projects/{code}` | - |
| list workflow | queryProcessDefinitionList | GET | `/projects/{pc}/process-definition/list` | - |
| search workflow | queryProcessDefinitionListPaging | GET | `/projects/{pc}/process-definition` | `searchVal`, `pageNo`, `pageSize` |
| get workflow | queryProcessDefinitionByCode | GET | `/projects/{pc}/process-definition/{code}` | - |
| list node | queryTaskDefinitionListPaging | GET | `/projects/{pc}/task-definition` | `searchWorkflowName`, `searchTaskName`, `taskType`, `pageNo`, `pageSize` |
| get node | queryTaskDefinitionDetail | GET | `/projects/{pc}/task-definition/{code}` | - |
| list process instance | queryProcessInstanceList | GET | `/projects/{pc}/process-instances` | `processDefineCode`, `searchVal`, `stateType`, `startDate`, `endDate`, `pageNo`, `pageSize` |
| get process instance | queryProcessInstanceById | GET | `/projects/{pc}/process-instances/{id}` | - |
| list task instances of a process instance | queryTaskListByProcessId | GET | `/projects/{pc}/process-instances/{id}/tasks` | - |
| search task instance | queryTaskListPaging | GET | `/projects/{pc}/task-instances` | `processInstanceId`, `searchVal`, `taskName`, `stateType`, `startDate`, `endDate`, `pageNo`, `pageSize` |
| start workflow | startProcessInstance | POST | `/projects/{pc}/executors/start-process-instance` | `processDefinitionCode`, `scheduleTime`, `failureStrategy`, `warningType`, `dryRun`, `workerGroup`, `startNodeList`, `timeout`, ... |
| get task log | queryLog | GET | `/log/{pc}/detail` | `taskInstanceId`, `skipLineNum`, `limit` |
| download task log | downloadTaskLog | GET | `/log/{pc}/download-log` | `taskInstanceId` |

Entity models (verified safe fields):

- `Project`: `id`, `code`, `name`, `description`, `createTime`, `updateTime`, `defCount`, `instRunningCount`.
- `ProcessDefinition`: `id`, `code`, `name`, `version`, `releaseState`, `projectCode`, `description`, `createTime`, `updateTime`, `executionType`.
- `TaskDefinition`: `id`, `code`, `name`, `version`, `taskType`, `taskParams` (bounded, not parsed), `workerGroup`, `createTime`, `updateTime`, `failRetryTimes`, `timeout`.
- `ProcessInstance`: `id`, `name`, `state` (`WorkflowExecutionStatus`), `processDefinitionCode`, `runTimes`, `host`, `startTime`, `endTime`, `duration`, `executorName`, `commandType`, `workerGroup`.
- `TaskInstance`: `id`, `name`, `taskType`, `processInstanceId`, `taskCode`, `state` (`TaskExecutionStatus`), `host`, `startTime`, `endTime`, `duration`, `retryTimes`, `appLink`, `logPath`, `executorName`.
- `ResponseTaskLog`: `{ "lineNum": <int>, "message": "<string>" }` (the log query `data`).

Status enums:

- `WorkflowExecutionStatus`: `SUBMITTED_SUCCESS`, `RUNNING_EXECUTION`, `READY_PAUSE`, `PAUSE`, `READY_STOP`, `STOP`, `FAILURE`, `SUCCESS`, `DELAY_EXECUTION`, `SERIAL_WAIT`, `READY_BLOCK`, `BLOCK`.
- `TaskExecutionStatus`: `SUBMITTED_SUCCESS`, `RUNNING_EXECUTION`, `PAUSE`, `STOP`, `FAILURE`, `SUCCESS`, `NEED_FAULT_TOLERANCE`, `KILL`, `DELAY_EXECUTION`, `FORCED_SUCCESS`, `DISPATCH`.

`TaskInstance.appLink` may hold a YARN tracking URL for Spark/Hive task types, but for SHELL nodes that internally run `spark-submit` the YARN application IDs and Spark UI links appear in the task log text; `extract_log_links` therefore parses the log.

### 4. Object type model

All tools share an `object_type` discriminator: `project`, `workflow`, `node`, `process_instance`, `task_instance`. Definitions (`project`, `workflow`, `node`) are addressed by `code` (a 64-bit DolphinScheduler code); instances (`process_instance`, `task_instance`) are addressed by `id` (an integer). `project_code` is required for every type except `project`.

### 5. Tool designs

Each scheduling tool accepts a JSON object input and returns a JSON object result. `object_type` is the enum `project | workflow | node | process_instance | task_instance`. `project_code` is a 64-bit integer required for every type except `project`. Definitions (`project`, `workflow`, `node`) are addressed by `code` (64-bit integer); instances (`process_instance`, `task_instance`) by `id` (integer). Every list/search result is bounded by `max_detail_items`; pagination by `max_page_size`; logs by `max_log_bytes`. The fields shown in result examples are the safe normalized subset returned to the MCP client; unknown upstream fields are dropped (see the entity models in Section 3).

#### `list_objects`

Enumerate objects of the requested `object_type` by calling the matching list endpoint.

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `object_type` | enum | yes | - | one of the five supported values |
| `project_code` | int64 | yes (except `project`) | - | scopes workflow/node/instance lists |
| `process_definition_code` | int64 | no | - | filters `process_instance` |
| `process_instance_id` | int | no | - | filters `task_instance` |
| `page_no` | int | no | `1` | 1-based page |
| `page_size` | int | no | `default_page_size` | capped at `max_page_size` |

The `project` and `workflow` list endpoints are unpaginated; their results are bounded by `max_detail_items`, and the returned `page_no`/`page_size` reflect that bound.

Result (`object_type` = `workflow`):

```json
{
  "object_type": "workflow",
  "items": [
    {"code": 18364130076160, "name": "etl_daily", "version": 3, "release_state": "ONLINE"}
  ],
  "page_no": 1,
  "page_size": 10,
  "total_count": 42,
  "truncated": false
}
```

Representative summary fields per type: `project` -> `code`, `name`, `def_count`, `inst_running_count`; `workflow` -> `code`, `name`, `version`, `release_state`; `node` -> `code`, `name`, `task_type`, `version`; `process_instance` -> `id`, `name`, `state`, `run_times`, `start_time`, `end_time`, `duration`; `task_instance` -> `id`, `name`, `task_type`, `state`, `process_instance_id`.

#### `get_object`

Return a specific object's attributes and, for `workflow` and `process_instance`, its related instances.

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `object_type` | enum | yes | - | one of the five supported values |
| `project_code` | int64 | yes (except `project`) | - | scopes the detail call |
| `code` | int64 | yes for `project`/`workflow`/`node` | - | definition code |
| `id` | int | yes for `process_instance` | - | instance id |
| `process_instance_id` | int | yes for `task_instance` | - | parent process instance |
| `task_instance_id` | int | yes for `task_instance` | - | task to resolve |

`workflow` calls `GET /projects/{pc}/process-definition/{code}` and then `GET /projects/{pc}/process-instances?processDefineCode={code}` for its process instances. `process_instance` calls `GET /projects/{pc}/process-instances/{id}` and then `GET /projects/{pc}/process-instances/{id}/tasks` for its task instances. DolphinScheduler 3.1.7 has no single-task-instance GET endpoint, so `task_instance` is resolved by fetching the parent's task list and matching `task_instance_id`; `process_instance_id` is therefore required for that type.

Result (`object_type` = `process_instance`):

```json
{
  "object_type": "process_instance",
  "object": {
    "id": 5567,
    "name": "etl_daily-20260807120000100",
    "state": "SUCCESS",
    "process_definition_code": 18364130076160,
    "run_times": 1,
    "host": "ds-worker-01:1234",
    "start_time": "2026-08-07 12:00:00",
    "end_time": "2026-08-07 12:05:33",
    "duration": 333,
    "executor_name": "admin"
  },
  "related": [
    {"id": 7788, "name": "run_spark_job", "task_type": "SHELL", "state": "SUCCESS", "process_instance_id": 5567}
  ]
}
```

For `project`, `workflow`, and `node`, `related` is omitted. For `task_instance`, `object` holds the matched task-instance attributes and `related` is omitted.

#### `search_objects`

Keyword search across object types with optional instance filters.

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `object_type` | enum | yes | - | one of the five supported values |
| `project_code` | int64 | yes (except `project`) | - | scopes the search |
| `search_val` | string | yes | - | non-empty, bounded keyword |
| `state_type` | enum | no | - | instance state filter; instances only |
| `start_date` | string | no | - | `yyyy-MM-dd HH:mm:ss`; instances only |
| `end_date` | string | no | - | `yyyy-MM-dd HH:mm:ss`; instances only |
| `page_no` | int | no | `1` | 1-based page |
| `page_size` | int | no | `default_page_size` | capped at `max_page_size` |

`search_val` maps to `searchVal` for `project`, `workflow`, `process_instance`, and `task_instance`, and to `searchTaskName` for `node`. `state_type`, `start_date`, and `end_date` apply only to `process_instance` and `task_instance`.

Result shape is identical to `list_objects` (`object_type`, `items`, `page_no`, `page_size`, `total_count`, `truncated`).

#### `start_workflow`

Start a process instance from a process definition code.

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `project_code` | int64 | yes | - | project scope |
| `process_definition_code` | int64 | yes | - | workflow to start |
| `dry_run` | int | no | `0` | `0` executes; `1` validates without executing |
| `start_node_list` | string | no | - | comma-separated node names; bounded |
| `timeout` | int | no | - | execution timeout in minutes |

Calls `POST /projects/{pc}/executors/start-process-instance` (form-encoded) with `processDefinitionCode` and safe defaults: `scheduleTime` empty, `failureStrategy` `CONTINUE`, `warningType` `NONE`, `dryRun` from input, `workerGroup` `default`, plus the standard DolphinScheduler executor defaults `taskDependType` `TASK_POST`, `execType` `START`, `runMode` `RUN_MODE_SERIAL`, `processInstancePriority` `MEDIUM`, `warningGroupId` empty, and `environmentCode` `-1`. Optional bounded `start_node_list` (`startNodeList`) and `timeout` pass through. It does not retry execution automatically.

Result:

```json
{
  "process_definition_code": 18364130076160,
  "process_instance_id": null,
  "dry_run": 0,
  "message": "success"
}
```

`process_instance_id` is `null` when the 3.1.7 response carries no process instance id (the typical case); it is populated only when the upstream returns one.

#### `get_task_log`

Read a task instance's bounded execution log.

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `project_code` | int64 | yes | - | project scope |
| `task_instance_id` | int | yes | - | task whose log is read |
| `skip_line_num` | int | no | `0` | line offset to start at |
| `limit` | int | no | `default_page_size` | lines to return; capped |

Calls `GET /log/{pc}/detail?taskInstanceId=&skipLineNum=&limit=`. Returns `task_instance_id`, `line_num` (the next read offset), the bounded `message`, and a `truncated` flag.

Result:

```json
{
  "task_instance_id": 7788,
  "line_num": 1000,
  "message": "INFO: starting spark-submit\napplication_1690000000000_0001\nSpark UI: http://rm-host:8088/proxy/application_1690000000000_0001",
  "truncated": false
}
```

A subsequent call passes `skip_line_num` equal to the previous `line_num` to page through the rest of the log.

#### `extract_log_links`

Fetch a task instance's full log and extract YARN application IDs and Spark UI / tracking URLs.

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `project_code` | int64 | yes | - | project scope |
| `task_instance_id` | int | yes | - | task whose log is parsed |

Fetches the full log via `GET /log/{pc}/download-log?taskInstanceId=` bounded by `max_log_bytes`, then extracts:
- YARN application IDs matching `application_\d+_\d+`.
- Spark UI / tracking URLs matching `http(s)://<host>/proxy/application_\d+_\d+` and `Spark UI:`-prefixed URLs.

Returns deduplicated, bounded `yarn_application_ids` and `spark_ui_urls`. No raw log is returned.

Result:

```json
{
  "task_instance_id": 7788,
  "yarn_application_ids": ["application_1690000000000_0001"],
  "spark_ui_urls": ["http://rm-host:8088/proxy/application_1690000000000_0001"]
}
```

### 6. Error mapping and result bounding

All scheduling tools reuse the status capability's error categories: HTTP 401 -> `AUTHENTICATION_FAILED`, 403 -> `PERMISSION_DENIED`, connection failure -> `CONNECTION_FAILED`, timeout -> `TIMEOUT`, HTTP 5xx or non-zero `Result.code` -> `UPSTREAM_ERROR`, unparseable envelope or unexpected `data` shape -> `UNEXPECTED_RESPONSE`. List and detail results are bounded by `max_detail_items`; pagination by `max_page_size`; logs by `max_log_bytes`. No raw HTTP artifacts, headers, cookies, credentials, the DolphinScheduler `msg` field (on success), or unbounded bodies reach the MCP client.

### 7. Execution safety

`start_workflow` is a state-changing operation. It starts a predefined workflow (not arbitrary code or SQL), so it does not require an interpreter-style allowlist. The `dry_run` parameter defaults to `0` (actual execution) to match the operator's intent; setting it to `1` performs a DS dry run that validates without executing. The configured token's DolphinScheduler permissions govern which workflows may be started. This trust implication is documented for operators.

## Risks / Trade-offs

- **[DolphinScheduler has no single-task-instance GET endpoint]** -> `get_object` for `task_instance` fetches the parent process instance's task list and matches by id, requiring `process_instance_id`.
- **[Task definitions search uses `searchTaskName`, not `searchVal`]** -> `search_objects` maps `search_val` to the correct parameter per object type.
- **[Business errors return HTTP 200 with a non-zero `code`]** -> the adapter inspects `Result.code` after a 2xx response and maps non-zero codes to `UPSTREAM_ERROR`.
- **[`start_workflow` executes real workflows]** -> accepted per direct user instruction; `dry_run` provides a validation-only mode; DS permissions constrain execution.
- **[Shell log link extraction is heuristic]** -> the regex patterns target the standard `spark-submit`/YARN log formats; unrecognized link formats are not returned. Parsing never returns raw log text.
- **[Log can be very large]** -> `get_task_log` is paginated and `extract_log_links` bounds the fetched log by `max_log_bytes`.
