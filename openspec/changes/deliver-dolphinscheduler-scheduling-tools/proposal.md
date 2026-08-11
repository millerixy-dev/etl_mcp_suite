## Why

The `deliver-dolphinscheduler-plugin-slice` change ships the DolphinScheduler status tool and plugin scaffolding, and the parent `build-plugin-mcp-stdio` change scoped DolphinScheduler as observational, status-only in V1. A direct user requirement now overrides that V1 scope: operators need to enumerate DolphinScheduler scheduling objects (projects, workflows, nodes, and their instances), inspect their attributes, search them, start a workflow, read a shell node's execution log, and extract the YARN application IDs and Spark UI links embedded in that log. None of these operations are covered by the status-only capability, so a new capability is needed, and the status capability's "exactly one tool / no workflow operations" prohibition must be lifted.

## What Changes

- Add a new `dolphinscheduler-scheduling-tools` capability with six tools: `list_objects`, `get_object`, `search_objects`, `start_workflow`, `get_task_log`, and `extract_log_links`.
- Implement the tools against the DolphinScheduler 3.1.7 REST API (context path `/dolphinscheduler`, `token`-header authentication, `Result` envelope with `code` `0` equal to success), reusing the status slice's gateway, asynchronous httpx adapter, error mapping, and composition root.
- `list_objects` enumerates projects, process definitions (workflows), task definitions (nodes), process instances, and task instances.
- `get_object` returns a specific object's attributes and, for definitions and process instances, its related instances.
- `search_objects` performs keyword search (and optional state/date filters) across the same object types.
- `start_workflow` starts a process instance from a process definition code with safe execution defaults.
- `get_task_log` reads a task instance's bounded execution log.
- `extract_log_links` fetches a shell node's log and extracts YARN application IDs and Spark UI / tracking URLs.
- Expand the DolphinScheduler configuration with `default_page_size`, `max_page_size`, and `max_log_bytes`.
- Lift the status capability's "exactly one tool" and "no workflow/task/instance operations" prohibition; those operations now live in the scheduling capability.
- Override the parent change's and `AGENTS.md`'s DolphinScheduler observational V1 scope for the scheduling surface.

## Capabilities

### New Capabilities

- `dolphinscheduler-scheduling-tools`: DolphinScheduler 3.1.7 scheduling object enumeration, attribute retrieval, keyword search, workflow execution, task-log retrieval, and YARN/Spark link extraction with bounded, redacted results and safe error mapping.

### Modified Capabilities

- `dolphinscheduler-status-tool`: the tool-set requirement no longer prohibits workflow, task, project, schedule, or instance operations (delivered by `dolphinscheduler-scheduling-tools`); the configuration requirement gains `default_page_size`, `max_page_size`, and `max_log_bytes`.

## Impact

- Extends `src/mcp_stdio/plugins/dolphinscheduler/` (built by `deliver-dolphinscheduler-plugin-slice`) with six scheduling tools in the gateway, service, and tool adapter.
- Reuses the existing `httpx` dependency; no new third-party dependency is introduced.
- Adds `default_page_size`, `max_page_size`, and `max_log_bytes` to `DolphinSchedulerSettings`.
- Expands the DolphinScheduler exact-tool-set contract test from one tool to seven.
- Promotes the DolphinScheduler plugin from observational to execution-capable (`start_workflow`) per direct user instruction, superseding the parent change's and `AGENTS.md`'s observational V1 scope for the scheduling surface; `AGENTS.md`'s DolphinScheduler scope line should be reconciled in this change.
- No change to the Hive or Zeppelin plugins, the shared core, or the runtime lifecycle.
