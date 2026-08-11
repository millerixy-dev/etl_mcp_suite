"""MCP- and httpx-independent DolphinScheduler gateway contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from mcp_stdio.core.errors import ToolError


@dataclass(frozen=True, slots=True)
class RawServer:
    """Safe, parsed fields of a single DolphinScheduler server entry."""

    host: str | None
    port: int | None
    res_info: str | None
    last_heartbeat_time: str | None


@dataclass(frozen=True, slots=True)
class RawProject:
    """Safe, parsed fields of a DolphinScheduler project."""

    code: int
    name: str | None = None
    description: str | None = None
    def_count: int | None = None
    inst_running_count: int | None = None


@dataclass(frozen=True, slots=True)
class RawWorkflow:
    """Safe, parsed fields of a DolphinScheduler process definition (workflow)."""

    code: int
    name: str | None = None
    version: int | None = None
    release_state: str | None = None
    project_code: int | None = None


@dataclass(frozen=True, slots=True)
class RawNode:
    """Safe, parsed fields of a DolphinScheduler task definition (node)."""

    code: int
    name: str | None = None
    task_type: str | None = None
    version: int | None = None


@dataclass(frozen=True, slots=True)
class RawProcessInstance:
    """Safe, parsed fields of a DolphinScheduler process instance."""

    id: int
    name: str | None = None
    state: str | None = None
    process_definition_code: int | None = None
    run_times: int | None = None
    host: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    duration: int | None = None
    executor_name: str | None = None


@dataclass(frozen=True, slots=True)
class RawTaskInstance:
    """Safe, parsed fields of a DolphinScheduler task instance."""

    id: int
    name: str | None = None
    task_type: str | None = None
    process_instance_id: int | None = None
    task_code: int | None = None
    state: str | None = None
    host: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    duration: int | None = None
    retry_times: int | None = None
    app_link: str | None = None
    log_path: str | None = None
    executor_name: str | None = None


@dataclass(frozen=True, slots=True)
class RawTaskLog:
    """One bounded page of a DolphinScheduler task log."""

    line_num: int
    message: str


@dataclass(frozen=True, slots=True)
class RawStartResult:
    """Safe, parsed fields of a start-process-instance response."""

    process_definition_code: int
    process_instance_id: int | None
    dry_run: int


T = TypeVar("T")


@dataclass(frozen=True)
class RawPage(Generic[T]):
    """A bounded page of parsed DolphinScheduler objects plus the upstream total."""

    items: tuple[T, ...]
    total_count: int


class DolphinSchedulerGatewayError(RuntimeError):
    """A categorized, safe failure crossing the DolphinScheduler gateway boundary."""

    def __init__(self, tool_error: ToolError) -> None:
        self.tool_error = tool_error
        super().__init__(tool_error.message)


class DolphinSchedulerGateway(Protocol):
    """REST operations required by the DolphinScheduler application service."""

    async def get_status(self) -> tuple[RawServer, ...]:
        """Return the parsed server entries from the configured status endpoint."""

        ...

    async def list_projects(self) -> tuple[RawProject, ...]:
        """Return all projects (unpaginated `/projects/list`)."""

        ...

    async def search_projects(
        self, *, search_val: str, page_no: int, page_size: int
    ) -> RawPage[RawProject]:
        """Return a page of projects matching `search_val` (`/projects`)."""

        ...

    async def get_project(self, *, code: int) -> RawProject:
        """Return one project (`/projects/{code}`)."""

        ...

    async def list_workflows(self, *, project_code: int) -> tuple[RawWorkflow, ...]:
        """Return all workflows in a project (unpaginated process-definition list)."""

        ...

    async def search_workflows(
        self, *, project_code: int, search_val: str, page_no: int, page_size: int
    ) -> RawPage[RawWorkflow]:
        """Return a page of workflows matching `search_val` (process-definition)."""

        ...

    async def get_workflow(self, *, project_code: int, code: int) -> RawWorkflow:
        """Return one workflow (`/projects/{pc}/process-definition/{code}`)."""

        ...

    async def query_nodes(
        self,
        *,
        project_code: int,
        search_task_name: str | None,
        page_no: int,
        page_size: int,
    ) -> RawPage[RawNode]:
        """Return a page of task definitions (nodes) in a project."""

        ...

    async def get_node(self, *, project_code: int, code: int) -> RawNode:
        """Return one node (`/projects/{pc}/task-definition/{code}`)."""

        ...

    async def query_process_instances(
        self,
        *,
        project_code: int,
        process_definition_code: int | None,
        search_val: str | None,
        state_type: str | None,
        start_date: str | None,
        end_date: str | None,
        page_no: int,
        page_size: int,
    ) -> RawPage[RawProcessInstance]:
        """Return a page of process instances with optional filters."""

        ...

    async def get_process_instance(
        self, *, project_code: int, process_instance_id: int
    ) -> RawProcessInstance:
        """Return one process instance (`/projects/{pc}/process-instances/{id}`)."""

        ...

    async def list_task_instances_of_process(
        self, *, project_code: int, process_instance_id: int
    ) -> tuple[RawTaskInstance, ...]:
        """Return the task instances of one process instance (unpaginated)."""

        ...

    async def query_task_instances(
        self,
        *,
        project_code: int,
        process_instance_id: int | None,
        search_val: str | None,
        task_name: str | None,
        state_type: str | None,
        start_date: str | None,
        end_date: str | None,
        page_no: int,
        page_size: int,
    ) -> RawPage[RawTaskInstance]:
        """Return a page of task instances with optional filters."""

        ...

    async def start_workflow(
        self,
        *,
        project_code: int,
        process_definition_code: int,
        dry_run: int,
        start_node_list: str | None,
        timeout: int | None,
    ) -> RawStartResult:
        """Start a process instance (`POST /executors/start-process-instance`)."""

        ...

    async def get_task_log(
        self, *, project_code: int, task_instance_id: int, skip_line_num: int, limit: int
    ) -> RawTaskLog:
        """Return one bounded page of a task log (`/log/{pc}/detail`)."""

        ...

    async def download_task_log(self, *, project_code: int, task_instance_id: int) -> str:
        """Return the full task log text bounded by `max_log_bytes`."""

        ...

    async def close(self) -> None:
        """Close owned HTTP resources."""

        ...
