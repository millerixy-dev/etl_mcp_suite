"""DolphinScheduler application service and result models."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict

from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation
from mcp_stdio.plugins.dolphinscheduler.gateway import (
    DolphinSchedulerGateway,
    DolphinSchedulerGatewayError,
    RawNode,
    RawPage,
    RawProcessInstance,
    RawProject,
    RawServer,
    RawStartResult,
    RawTaskInstance,
    RawTaskLog,
    RawWorkflow,
)

_OBJECT_TYPES = ("project", "workflow", "node", "process_instance", "task_instance")
_DEFINITION_TYPES = ("project", "workflow", "node")
_INSTANCE_TYPES = ("process_instance", "task_instance")

_YARN_APPLICATION_ID = re.compile(r"application_\d+_\d+")
_SPARK_PROXY_URL = re.compile(r"https?://\S*/proxy/application_\d+_\d+\S*")
_SPARK_UI_LINE = re.compile(r"Spark UI:\s*(\S+)")


# --------------------------------------------------------------------------- status


class ServerSummary(BaseModel):
    """Safe, normalized fields of a single DolphinScheduler server entry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    host: str | None = None
    port: int | None = None
    res_info: str | None = None
    last_heartbeat_time: str | None = None


class ServerStatusResult(BaseModel):
    """Normalized DolphinScheduler server-status tool result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    available: bool
    status: Literal["HEALTHY", "UNHEALTHY"]
    server_count: int
    servers: tuple[ServerSummary, ...]


# --------------------------------------------------------------------------- summaries


class ProjectSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: int
    name: str | None = None
    description: str | None = None
    def_count: int | None = None
    inst_running_count: int | None = None


class WorkflowSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: int
    name: str | None = None
    version: int | None = None
    release_state: str | None = None
    project_code: int | None = None


class NodeSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: int
    name: str | None = None
    task_type: str | None = None
    version: int | None = None


class ProcessInstanceSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

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


class TaskInstanceSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

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
    executor_name: str | None = None


ObjectSummary = (
    ProjectSummary | WorkflowSummary | NodeSummary | ProcessInstanceSummary | TaskInstanceSummary
)

_RawT = TypeVar("_RawT")


# --------------------------------------------------------------------------- results


class ListObjectsResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    object_type: str
    items: tuple[ObjectSummary, ...]
    page_no: int
    page_size: int
    total_count: int
    truncated: bool


class GetObjectResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    object_type: str
    object: ObjectSummary
    related: tuple[ObjectSummary, ...] | None = None


class StartWorkflowResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    process_definition_code: int
    process_instance_id: int | None
    dry_run: int
    message: str


class GetTaskLogResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_instance_id: int
    line_num: int
    message: str
    truncated: bool


class ExtractLogLinksResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_instance_id: int
    yarn_application_ids: tuple[str, ...]
    spark_ui_urls: tuple[str, ...]


# --------------------------------------------------------------------------- service


class DolphinSchedulerStatusService:
    """Coordinate the DolphinScheduler status and scheduling use cases."""

    def __init__(
        self,
        *,
        gateway: DolphinSchedulerGateway,
        max_detail_items: int,
        default_page_size: int = 10,
        max_page_size: int = 100,
        max_log_bytes: int = 1_048_576,
    ) -> None:
        self._gateway = gateway
        self._max_detail_items = max_detail_items
        self._default_page_size = default_page_size
        self._max_page_size = max_page_size
        self._max_log_bytes = max_log_bytes

    # -- status

    async def get_server_status(self) -> ServerStatusResult:
        raw = await self._gateway.get_status()
        capped = raw[: self._max_detail_items]
        summaries = tuple(_to_summary(server) for server in capped)
        status: Literal["HEALTHY", "UNHEALTHY"] = "HEALTHY" if capped else "UNHEALTHY"
        return ServerStatusResult(
            available=True,
            status=status,
            server_count=len(summaries),
            servers=summaries,
        )

    # -- list

    async def list_objects(
        self,
        *,
        object_type: str,
        project_code: int | None = None,
        process_definition_code: int | None = None,
        process_instance_id: int | None = None,
        page_no: int = 1,
        page_size: int | None = None,
    ) -> ListObjectsResult:
        self._require_object_type(object_type, ToolOperation.LIST_OBJECTS)
        project_code = self._require_project_code(
            object_type, project_code, ToolOperation.LIST_OBJECTS
        )
        page_no = _page_no(page_no)
        page_size = self._capped_page_size(page_size)

        if object_type == "project":
            items = await self._gateway.list_projects()
            return self._unpaginated(object_type, items, page_no, page_size, _to_project_summary)
        if object_type == "workflow":
            items = await self._gateway.list_workflows(project_code=project_code)
            return self._unpaginated(object_type, items, page_no, page_size, _to_workflow_summary)
        if object_type == "node":
            page = await self._gateway.query_nodes(
                project_code=project_code,
                search_task_name=None,
                page_no=page_no,
                page_size=page_size,
            )
            return self._paged(object_type, page, page_no, page_size, _to_node_summary)
        if object_type == "process_instance":
            page = await self._gateway.query_process_instances(
                project_code=project_code,
                process_definition_code=process_definition_code,
                search_val=None,
                state_type=None,
                start_date=None,
                end_date=None,
                page_no=page_no,
                page_size=page_size,
            )
            return self._paged(object_type, page, page_no, page_size, _to_process_instance_summary)
        page = await self._gateway.query_task_instances(
            project_code=project_code,
            process_instance_id=process_instance_id,
            search_val=None,
            task_name=None,
            state_type=None,
            start_date=None,
            end_date=None,
            page_no=page_no,
            page_size=page_size,
        )
        return self._paged(object_type, page, page_no, page_size, _to_task_instance_summary)

    # -- get

    async def get_object(
        self,
        *,
        object_type: str,
        project_code: int | None = None,
        code: int | None = None,
        id: int | None = None,
        process_instance_id: int | None = None,
        task_instance_id: int | None = None,
    ) -> GetObjectResult:
        operation = ToolOperation.GET_OBJECT
        self._require_object_type(object_type, operation)
        project_code = self._require_project_code(object_type, project_code, operation)

        if object_type == "project":
            code = self._require(code, "code", operation)
            obj = await self._gateway.get_project(code=code)
            return GetObjectResult(object_type=object_type, object=_to_project_summary(obj))
        if object_type == "workflow":
            code = self._require(code, "code", operation)
            obj = await self._gateway.get_workflow(project_code=project_code, code=code)
            related_page = await self._gateway.query_process_instances(
                project_code=project_code,
                process_definition_code=code,
                search_val=None,
                state_type=None,
                start_date=None,
                end_date=None,
                page_no=1,
                page_size=self._max_page_size,
            )
            related = tuple(
                _to_process_instance_summary(i)
                for i in related_page.items[: self._max_detail_items]
            )
            return GetObjectResult(
                object_type=object_type, object=_to_workflow_summary(obj), related=related
            )
        if object_type == "node":
            code = self._require(code, "code", operation)
            obj = await self._gateway.get_node(project_code=project_code, code=code)
            return GetObjectResult(object_type=object_type, object=_to_node_summary(obj))
        if object_type == "process_instance":
            id = self._require(id, "id", operation)
            obj = await self._gateway.get_process_instance(
                project_code=project_code,
                process_instance_id=id,
            )
            tasks = await self._gateway.list_task_instances_of_process(
                project_code=project_code,
                process_instance_id=id,
            )
            related = tuple(_to_task_instance_summary(i) for i in tasks[: self._max_detail_items])
            return GetObjectResult(
                object_type=object_type, object=_to_process_instance_summary(obj), related=related
            )
        process_instance_id = self._require(process_instance_id, "process_instance_id", operation)
        task_instance_id = self._require(task_instance_id, "task_instance_id", operation)
        tasks = await self._gateway.list_task_instances_of_process(
            project_code=project_code,
            process_instance_id=process_instance_id,
        )
        match = next((t for t in tasks if t.id == task_instance_id), None)
        if match is None:
            raise self._invalid_input(
                operation, "task instance was not found in the process instance"
            )
        return GetObjectResult(object_type=object_type, object=_to_task_instance_summary(match))

    # -- search

    async def search_objects(
        self,
        *,
        object_type: str,
        project_code: int | None = None,
        search_val: str,
        state_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        page_no: int = 1,
        page_size: int | None = None,
    ) -> ListObjectsResult:
        operation = ToolOperation.SEARCH_OBJECTS
        self._require_object_type(object_type, operation)
        project_code = self._require_project_code(object_type, project_code, operation)
        if not search_val or not search_val.strip():
            raise self._invalid_input(operation, "search_val must be a non-empty string")
        page_no = _page_no(page_no)
        page_size = self._capped_page_size(page_size)

        if object_type == "project":
            page = await self._gateway.search_projects(
                search_val=search_val, page_no=page_no, page_size=page_size
            )
            return self._paged(object_type, page, page_no, page_size, _to_project_summary)
        if object_type == "workflow":
            page = await self._gateway.search_workflows(
                project_code=project_code,
                search_val=search_val,
                page_no=page_no,
                page_size=page_size,
            )
            return self._paged(object_type, page, page_no, page_size, _to_workflow_summary)
        if object_type == "node":
            page = await self._gateway.query_nodes(
                project_code=project_code,
                search_task_name=search_val,
                page_no=page_no,
                page_size=page_size,
            )
            return self._paged(object_type, page, page_no, page_size, _to_node_summary)
        if object_type == "process_instance":
            page = await self._gateway.query_process_instances(
                project_code=project_code,
                process_definition_code=None,
                search_val=search_val,
                state_type=state_type,
                start_date=start_date,
                end_date=end_date,
                page_no=page_no,
                page_size=page_size,
            )
            return self._paged(object_type, page, page_no, page_size, _to_process_instance_summary)
        page = await self._gateway.query_task_instances(
            project_code=project_code,
            process_instance_id=None,
            search_val=search_val,
            task_name=None,
            state_type=state_type,
            start_date=start_date,
            end_date=end_date,
            page_no=page_no,
            page_size=page_size,
        )
        return self._paged(object_type, page, page_no, page_size, _to_task_instance_summary)

    # -- start

    async def start_workflow(
        self,
        *,
        project_code: int,
        process_definition_code: int,
        dry_run: int = 0,
        start_node_list: str | None = None,
        timeout: int | None = None,
    ) -> StartWorkflowResult:
        operation = ToolOperation.START_WORKFLOW
        if dry_run not in (0, 1):
            raise self._invalid_input(operation, "dry_run must be 0 or 1")
        raw: RawStartResult = await self._gateway.start_workflow(
            project_code=project_code,
            process_definition_code=process_definition_code,
            dry_run=dry_run,
            start_node_list=start_node_list,
            timeout=timeout,
        )
        message = (
            "dry run validation requested" if dry_run == 1 else "start process instance success"
        )
        return StartWorkflowResult(
            process_definition_code=raw.process_definition_code,
            process_instance_id=raw.process_instance_id,
            dry_run=raw.dry_run,
            message=message,
        )

    # -- logs

    async def get_task_log(
        self,
        *,
        project_code: int,
        task_instance_id: int,
        skip_line_num: int = 0,
        limit: int | None = None,
    ) -> GetTaskLogResult:
        operation = ToolOperation.GET_TASK_LOG
        if skip_line_num < 0:
            raise self._invalid_input(operation, "skip_line_num must be non-negative")
        cap = self._default_page_size if limit is None else min(limit, self._max_page_size)
        if cap < 1:
            cap = self._default_page_size
        raw: RawTaskLog = await self._gateway.get_task_log(
            project_code=project_code,
            task_instance_id=task_instance_id,
            skip_line_num=skip_line_num,
            limit=cap,
        )
        return GetTaskLogResult(
            task_instance_id=task_instance_id,
            line_num=raw.line_num,
            message=raw.message,
            truncated=False,
        )

    async def extract_log_links(
        self,
        *,
        project_code: int,
        task_instance_id: int,
    ) -> ExtractLogLinksResult:
        log_text = await self._gateway.download_task_log(
            project_code=project_code, task_instance_id=task_instance_id
        )
        yarn_ids = _dedupe(_YARN_APPLICATION_ID.findall(log_text))[: self._max_detail_items]
        spark_urls = _dedupe(_SPARK_PROXY_URL.findall(log_text))
        for match in _SPARK_UI_LINE.findall(log_text):
            if match.startswith("http"):
                spark_urls.append(match)
        spark_urls = _dedupe(spark_urls)[: self._max_detail_items]
        return ExtractLogLinksResult(
            task_instance_id=task_instance_id,
            yarn_application_ids=tuple(yarn_ids),
            spark_ui_urls=tuple(spark_urls),
        )

    # -- helpers

    def _require_object_type(self, object_type: str, operation: ToolOperation) -> None:
        if object_type not in _OBJECT_TYPES:
            raise self._invalid_input(operation, "object_type must be one of the supported values")

    def _require_project_code(
        self, object_type: str, project_code: int | None, operation: ToolOperation
    ) -> int:
        if object_type == "project":
            return 0
        if project_code is None:
            raise self._invalid_input(operation, "project_code is required for this object_type")
        return project_code

    def _require(self, value: int | None, name: str, operation: ToolOperation) -> int:
        if value is None:
            raise self._invalid_input(operation, f"{name} is required for this object_type")
        return value

    def _capped_page_size(self, page_size: int | None) -> int:
        if page_size is None or page_size < 1:
            return self._default_page_size
        return min(page_size, self._max_page_size)

    def _invalid_input(
        self, operation: ToolOperation, explanation: str
    ) -> DolphinSchedulerGatewayError:
        return DolphinSchedulerGatewayError(
            ToolError.create(
                category=ErrorCategory.INVALID_INPUT,
                operation=operation,
                retryable=False,
                identifiers={},
                explanation=explanation,
            )
        )

    def _unpaginated(
        self,
        object_type: str,
        items: tuple[_RawT, ...],
        page_no: int,
        page_size: int,
        mapper: Callable[[_RawT], ObjectSummary],
    ) -> ListObjectsResult:
        total = len(items)
        capped = items[: self._max_detail_items]
        summaries = tuple(mapper(item) for item in capped)
        return ListObjectsResult(
            object_type=object_type,
            items=summaries,
            page_no=page_no,
            page_size=page_size,
            total_count=total,
            truncated=total > len(capped),
        )

    def _paged(
        self,
        object_type: str,
        page: RawPage[_RawT],
        page_no: int,
        page_size: int,
        mapper: Callable[[_RawT], ObjectSummary],
    ) -> ListObjectsResult:
        capped = page.items[: self._max_detail_items]
        summaries = tuple(mapper(item) for item in capped)
        return ListObjectsResult(
            object_type=object_type,
            items=summaries,
            page_no=page_no,
            page_size=page_size,
            total_count=page.total_count,
            truncated=page.total_count > page_no * page_size,
        )


def _page_no(page_no: int) -> int:
    return page_no if page_no >= 1 else 1


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _to_summary(server: RawServer) -> ServerSummary:
    return ServerSummary(
        host=server.host,
        port=server.port,
        res_info=server.res_info,
        last_heartbeat_time=server.last_heartbeat_time,
    )


def _to_project_summary(item: RawProject) -> ProjectSummary:
    return ProjectSummary(
        code=item.code,
        name=item.name,
        description=item.description,
        def_count=item.def_count,
        inst_running_count=item.inst_running_count,
    )


def _to_workflow_summary(item: RawWorkflow) -> WorkflowSummary:
    return WorkflowSummary(
        code=item.code,
        name=item.name,
        version=item.version,
        release_state=item.release_state,
        project_code=item.project_code,
    )


def _to_node_summary(item: RawNode) -> NodeSummary:
    return NodeSummary(
        code=item.code,
        name=item.name,
        task_type=item.task_type,
        version=item.version,
    )


def _to_process_instance_summary(item: RawProcessInstance) -> ProcessInstanceSummary:
    return ProcessInstanceSummary(
        id=item.id,
        name=item.name,
        state=item.state,
        process_definition_code=item.process_definition_code,
        run_times=item.run_times,
        host=item.host,
        start_time=item.start_time,
        end_time=item.end_time,
        duration=item.duration,
        executor_name=item.executor_name,
    )


def _to_task_instance_summary(item: RawTaskInstance) -> TaskInstanceSummary:
    return TaskInstanceSummary(
        id=item.id,
        name=item.name,
        task_type=item.task_type,
        process_instance_id=item.process_instance_id,
        task_code=item.task_code,
        state=item.state,
        host=item.host,
        start_time=item.start_time,
        end_time=item.end_time,
        duration=item.duration,
        retry_times=item.retry_times,
        app_link=item.app_link,
        executor_name=item.executor_name,
    )
