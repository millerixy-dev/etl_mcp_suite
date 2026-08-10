"""Asynchronous DolphinScheduler HTTP adapter behind the gateway port."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypeVar, cast

import httpx

from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation
from mcp_stdio.plugins.dolphinscheduler.config import (
    DolphinSchedulerSecrets,
    DolphinSchedulerSettings,
)
from mcp_stdio.plugins.dolphinscheduler.gateway import (
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

logger = logging.getLogger("mcp_stdio.dolphinscheduler")

_SUCCESS_CODE = 0
_RETRYABLE = frozenset({ErrorCategory.TIMEOUT, ErrorCategory.CONNECTION_FAILED})


class DolphinSchedulerHttpClient:
    """httpx-backed DolphinScheduler gateway with one lazy client per process."""

    def __init__(
        self,
        *,
        settings: DolphinSchedulerSettings,
        secrets: DolphinSchedulerSecrets,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._secrets = secrets
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._closed = False

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._settings.base_url,
                timeout=self._settings.request_timeout_seconds,
                transport=self._transport,
                trust_env=False,
            )
        return self._client

    # ------------------------------------------------------------------ status

    async def get_status(self) -> tuple[RawServer, ...]:
        data = await self._request(
            "GET", self._settings.status_path, operation=ToolOperation.GET_SERVER_STATUS
        )
        if not isinstance(data, list):
            raise self._gateway_error(
                ErrorCategory.UNEXPECTED_RESPONSE, ToolOperation.GET_SERVER_STATUS
            )
        return self._parse_servers(cast(list[object], data))

    # ------------------------------------------------------------------ projects

    async def list_projects(self) -> tuple[RawProject, ...]:
        data = await self._request("GET", "/projects/list", operation=ToolOperation.LIST_OBJECTS)
        return self._parse_project_list(data)

    async def search_projects(
        self, *, search_val: str, page_no: int, page_size: int
    ) -> RawPage[RawProject]:
        data = await self._request(
            "GET",
            "/projects",
            params={"searchVal": search_val, "pageNo": page_no, "pageSize": page_size},
            operation=ToolOperation.SEARCH_OBJECTS,
        )
        return self._parse_page(data, _parse_project)

    async def get_project(self, *, code: int) -> RawProject:
        data = await self._request("GET", f"/projects/{code}", operation=ToolOperation.GET_OBJECT)
        return self._parse_single(data, _parse_project)

    # ------------------------------------------------------------------ workflows

    async def list_workflows(self, *, project_code: int) -> tuple[RawWorkflow, ...]:
        data = await self._request(
            "GET",
            f"/projects/{project_code}/process-definition/list",
            operation=ToolOperation.LIST_OBJECTS,
        )
        return self._parse_workflow_list(data)

    async def search_workflows(
        self, *, project_code: int, search_val: str, page_no: int, page_size: int
    ) -> RawPage[RawWorkflow]:
        data = await self._request(
            "GET",
            f"/projects/{project_code}/process-definition",
            params={"searchVal": search_val, "pageNo": page_no, "pageSize": page_size},
            operation=ToolOperation.SEARCH_OBJECTS,
        )
        return self._parse_page(data, _parse_workflow)

    async def get_workflow(self, *, project_code: int, code: int) -> RawWorkflow:
        data = await self._request(
            "GET",
            f"/projects/{project_code}/process-definition/{code}",
            operation=ToolOperation.GET_OBJECT,
        )
        return self._parse_single(data, _parse_workflow)

    # ------------------------------------------------------------------ nodes

    async def query_nodes(
        self,
        *,
        project_code: int,
        search_task_name: str | None,
        page_no: int,
        page_size: int,
    ) -> RawPage[RawNode]:
        params: dict[str, Any] = {"pageNo": page_no, "pageSize": page_size}
        if search_task_name:
            params["searchTaskName"] = search_task_name
        data = await self._request(
            "GET",
            f"/projects/{project_code}/task-definition",
            params=params,
            operation=ToolOperation.LIST_OBJECTS,
        )
        return self._parse_page(data, _parse_node)

    async def get_node(self, *, project_code: int, code: int) -> RawNode:
        data = await self._request(
            "GET",
            f"/projects/{project_code}/task-definition/{code}",
            operation=ToolOperation.GET_OBJECT,
        )
        return self._parse_single(data, _parse_node)

    # ------------------------------------------------------------------ process instances

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
        params = _build_instance_params(
            process_definition_code=process_definition_code,
            search_val=search_val,
            state_type=state_type,
            start_date=start_date,
            end_date=end_date,
            page_no=page_no,
            page_size=page_size,
            definition_param="processDefineCode",
        )
        data = await self._request(
            "GET",
            f"/projects/{project_code}/process-instances",
            params=params,
            operation=ToolOperation.LIST_OBJECTS,
        )
        return self._parse_page(data, _parse_process_instance)

    async def get_process_instance(
        self, *, project_code: int, process_instance_id: int
    ) -> RawProcessInstance:
        data = await self._request(
            "GET",
            f"/projects/{project_code}/process-instances/{process_instance_id}",
            operation=ToolOperation.GET_OBJECT,
        )
        return self._parse_single(data, _parse_process_instance)

    async def list_task_instances_of_process(
        self, *, project_code: int, process_instance_id: int
    ) -> tuple[RawTaskInstance, ...]:
        data = await self._request(
            "GET",
            f"/projects/{project_code}/process-instances/{process_instance_id}/tasks",
            operation=ToolOperation.LIST_OBJECTS,
        )
        items = _as_list(data, ToolOperation.LIST_OBJECTS, self._gateway_error)
        return tuple(
            filtered
            for filtered in (_parse_task_instance(i) for i in items)
            if filtered is not None
        )

    # ------------------------------------------------------------------ task instances

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
        params = _build_instance_params(
            process_definition_code=None,
            search_val=search_val,
            state_type=state_type,
            start_date=start_date,
            end_date=end_date,
            page_no=page_no,
            page_size=page_size,
            definition_param="processDefineCode",
        )
        if process_instance_id is not None:
            params["processInstanceId"] = process_instance_id
        if task_name:
            params["taskName"] = task_name
        data = await self._request(
            "GET",
            f"/projects/{project_code}/task-instances",
            params=params,
            operation=ToolOperation.LIST_OBJECTS,
        )
        return self._parse_page(data, _parse_task_instance)

    # ------------------------------------------------------------------ execution

    async def start_workflow(
        self,
        *,
        project_code: int,
        process_definition_code: int,
        dry_run: int,
        start_node_list: str | None,
        timeout: int | None,
    ) -> RawStartResult:
        form: dict[str, Any] = {
            "processDefinitionCode": process_definition_code,
            "scheduleTime": "",
            "failureStrategy": "CONTINUE",
            "startNodeList": start_node_list or "",
            "taskDependType": "TASK_POST",
            "execType": "START",
            "warningType": "NONE",
            "warningGroupId": "",
            "runMode": "RUN_MODE_SERIAL",
            "processInstancePriority": "MEDIUM",
            "workerGroup": "default",
            "environmentCode": "-1",
            "dryRun": dry_run,
        }
        if timeout is not None:
            form["timeout"] = timeout
        data = await self._request(
            "POST",
            f"/projects/{project_code}/executors/start-process-instance",
            data=form,
            operation=ToolOperation.START_WORKFLOW,
        )
        instance_id = None
        if isinstance(data, dict):
            instance_id = _opt_int(cast(dict[str, Any], data).get("processInstanceId"))
        elif isinstance(data, int) and not isinstance(data, bool):
            instance_id = data
        return RawStartResult(
            process_definition_code=process_definition_code,
            process_instance_id=instance_id,
            dry_run=dry_run,
        )

    # ------------------------------------------------------------------ logs

    async def get_task_log(
        self, *, project_code: int, task_instance_id: int, skip_line_num: int, limit: int
    ) -> RawTaskLog:
        data = await self._request(
            "GET",
            f"/log/{project_code}/detail",
            params={
                "taskInstanceId": task_instance_id,
                "skipLineNum": skip_line_num,
                "limit": limit,
            },
            operation=ToolOperation.GET_TASK_LOG,
        )
        entries = _as_list(data, ToolOperation.GET_TASK_LOG, self._gateway_error)
        messages: list[str] = []
        next_line = skip_line_num
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            typed = cast(dict[str, Any], entry)
            message = _opt_str(typed.get("message"))
            if message:
                messages.append(message)
            line_num = _opt_int(typed.get("lineNum"))
            if line_num is not None:
                next_line = line_num
        return RawTaskLog(line_num=next_line, message="\n".join(messages))

    async def download_task_log(self, *, project_code: int, task_instance_id: int) -> str:
        client = await self._ensure_client()
        headers = self._auth_headers()
        operation = ToolOperation.EXTRACT_LOG_LINKS
        try:
            response = await client.request(
                "GET",
                f"/log/{project_code}/download-log",
                params={"taskInstanceId": task_instance_id},
                headers=headers,
            )
        except httpx.ConnectTimeout:
            raise self._gateway_error(ErrorCategory.TIMEOUT, operation) from None
        except httpx.ReadTimeout:
            raise self._gateway_error(ErrorCategory.TIMEOUT, operation) from None
        except (httpx.ConnectError, httpx.RemoteProtocolError):
            raise self._gateway_error(ErrorCategory.CONNECTION_FAILED, operation) from None
        except httpx.HTTPError:
            raise self._gateway_error(ErrorCategory.UPSTREAM_ERROR, operation) from None

        status_code = response.status_code
        if status_code == 401:
            raise self._gateway_error(ErrorCategory.AUTHENTICATION_FAILED, operation)
        if status_code == 403:
            raise self._gateway_error(ErrorCategory.PERMISSION_DENIED, operation)
        if status_code >= 400:
            raise self._gateway_error(ErrorCategory.UPSTREAM_ERROR, operation)

        content = response.content
        limit = self._settings.max_log_bytes
        truncated = len(content) > limit
        if truncated:
            content = content[:limit]
        return content.decode("utf-8", errors="replace")

    # ------------------------------------------------------------------ helpers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        operation: ToolOperation,
        max_bytes: int | None = None,
    ) -> object:
        client = await self._ensure_client()
        headers = self._auth_headers()
        try:
            response = await client.request(method, path, params=params, data=data, headers=headers)
        except httpx.ConnectTimeout:
            raise self._gateway_error(ErrorCategory.TIMEOUT, operation) from None
        except httpx.ReadTimeout:
            raise self._gateway_error(ErrorCategory.TIMEOUT, operation) from None
        except (httpx.ConnectError, httpx.RemoteProtocolError):
            raise self._gateway_error(ErrorCategory.CONNECTION_FAILED, operation) from None
        except httpx.HTTPError:
            raise self._gateway_error(ErrorCategory.UPSTREAM_ERROR, operation) from None

        bounded = await self._bound_response(response, max_bytes=max_bytes)
        status_code = bounded.status_code
        if status_code == 401:
            raise self._gateway_error(ErrorCategory.AUTHENTICATION_FAILED, operation)
        if status_code == 403:
            raise self._gateway_error(ErrorCategory.PERMISSION_DENIED, operation)
        if status_code >= 400:
            raise self._gateway_error(ErrorCategory.UPSTREAM_ERROR, operation)

        try:
            document = bounded.json()
        except Exception:
            raise self._gateway_error(ErrorCategory.UNEXPECTED_RESPONSE, operation) from None
        if not isinstance(document, dict):
            raise self._gateway_error(ErrorCategory.UNEXPECTED_RESPONSE, operation)
        typed = cast(dict[str, Any], document)
        code = typed.get("code")
        if not isinstance(code, int) or isinstance(code, bool):
            raise self._gateway_error(ErrorCategory.UNEXPECTED_RESPONSE, operation)
        if code != _SUCCESS_CODE:
            raise self._gateway_error(ErrorCategory.UPSTREAM_ERROR, operation)
        return typed.get("data")

    async def _bound_response(
        self, response: httpx.Response, *, max_bytes: int | None = None
    ) -> httpx.Response:
        limit = max_bytes if max_bytes is not None else self._settings.max_response_bytes
        if len(response.content) > limit:
            raise self._gateway_error(
                ErrorCategory.UNEXPECTED_RESPONSE, ToolOperation.GET_SERVER_STATUS
            )
        return response

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._secrets.token is not None:
            headers["token"] = self._secrets.token.get_secret_value()
        return headers

    def _parse_servers(self, items: list[object]) -> tuple[RawServer, ...]:
        servers: list[RawServer] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            entry = cast(dict[str, Any], item)
            servers.append(
                RawServer(
                    host=_opt_str(entry.get("host")),
                    port=_opt_int(entry.get("port")),
                    res_info=_opt_str(entry.get("resInfo")),
                    last_heartbeat_time=_opt_str(entry.get("lastHeartbeatTime")),
                )
            )
        return tuple(servers)

    def _parse_project_list(self, data: object) -> tuple[RawProject, ...]:
        items = _as_list(data, ToolOperation.LIST_OBJECTS, self._gateway_error)
        return tuple(
            filtered for filtered in (_parse_project(i) for i in items) if filtered is not None
        )

    def _parse_workflow_list(self, data: object) -> tuple[RawWorkflow, ...]:
        items = _as_list(data, ToolOperation.LIST_OBJECTS, self._gateway_error)
        return tuple(
            filtered for filtered in (_parse_workflow(i) for i in items) if filtered is not None
        )

    def _parse_page(
        self,
        data: object,
        parser: Callable[[object], _ParsedT | None],
    ) -> RawPage[_ParsedT]:
        operation = ToolOperation.LIST_OBJECTS
        if not isinstance(data, dict):
            raise self._gateway_error(ErrorCategory.UNEXPECTED_RESPONSE, operation)
        typed = cast(dict[str, Any], data)
        raw_list = typed.get("totalList")
        if not isinstance(raw_list, list):
            raise self._gateway_error(ErrorCategory.UNEXPECTED_RESPONSE, operation)
        total = typed.get("total")
        if not isinstance(total, int) or isinstance(total, bool):
            total = 0
        items = tuple(
            filtered
            for filtered in (parser(item) for item in cast(list[object], raw_list))
            if filtered is not None
        )
        return RawPage(items=items, total_count=total)

    def _parse_single(
        self,
        data: object,
        parser: Callable[[object], _ParsedT | None],
    ) -> _ParsedT:
        operation = ToolOperation.GET_OBJECT
        if not isinstance(data, dict):
            raise self._gateway_error(ErrorCategory.UNEXPECTED_RESPONSE, operation)
        parsed = parser(cast(dict[str, Any], data))
        if parsed is None:
            raise self._gateway_error(ErrorCategory.UNEXPECTED_RESPONSE, operation)
        return parsed

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                logger.debug("error closing dolphinscheduler http client", exc_info=True)
            self._client = None

    def _gateway_error(
        self, category: ErrorCategory, operation: ToolOperation
    ) -> DolphinSchedulerGatewayError:
        return DolphinSchedulerGatewayError(
            ToolError.create(
                category=category,
                operation=operation,
                retryable=category in _RETRYABLE,
                identifiers={},
            )
        )


_ParsedT = TypeVar("_ParsedT")


def _as_list(
    data: object,
    operation: ToolOperation,
    gateway_error: Callable[[ErrorCategory, ToolOperation], DolphinSchedulerGatewayError],
) -> list[object]:
    if not isinstance(data, list):
        raise gateway_error(ErrorCategory.UNEXPECTED_RESPONSE, operation)
    return cast(list[object], data)


def _build_instance_params(
    *,
    process_definition_code: int | None,
    search_val: str | None,
    state_type: str | None,
    start_date: str | None,
    end_date: str | None,
    page_no: int,
    page_size: int,
    definition_param: str,
) -> dict[str, Any]:
    params: dict[str, Any] = {"pageNo": page_no, "pageSize": page_size}
    if process_definition_code is not None:
        params[definition_param] = process_definition_code
    if search_val:
        params["searchVal"] = search_val
    if state_type:
        params["stateType"] = state_type
    if start_date:
        params["startDate"] = start_date
    if end_date:
        params["endDate"] = end_date
    return params


def _parse_project(item: object) -> RawProject | None:
    if not isinstance(item, dict):
        return None
    entry = cast(dict[str, Any], item)
    code = _opt_int(entry.get("code"))
    if code is None:
        return None
    return RawProject(
        code=code,
        name=_opt_str(entry.get("name")),
        description=_opt_str(entry.get("description")),
        def_count=_opt_int(entry.get("defCount")),
        inst_running_count=_opt_int(entry.get("instRunningCount")),
    )


def _parse_workflow(item: object) -> RawWorkflow | None:
    if not isinstance(item, dict):
        return None
    entry = cast(dict[str, Any], item)
    code = _opt_int(entry.get("code"))
    if code is None:
        return None
    return RawWorkflow(
        code=code,
        name=_opt_str(entry.get("name")),
        version=_opt_int(entry.get("version")),
        release_state=_opt_str(entry.get("releaseState")),
        project_code=_opt_int(entry.get("projectCode")),
    )


def _parse_node(item: object) -> RawNode | None:
    if not isinstance(item, dict):
        return None
    entry = cast(dict[str, Any], item)
    code = _opt_int(entry.get("code"))
    if code is None:
        return None
    return RawNode(
        code=code,
        name=_opt_str(entry.get("name")),
        task_type=_opt_str(entry.get("taskType")),
        version=_opt_int(entry.get("version")),
    )


def _parse_process_instance(item: object) -> RawProcessInstance | None:
    if not isinstance(item, dict):
        return None
    entry = cast(dict[str, Any], item)
    instance_id = _opt_int(entry.get("id"))
    if instance_id is None:
        return None
    return RawProcessInstance(
        id=instance_id,
        name=_opt_str(entry.get("name")),
        state=_opt_str(entry.get("state")),
        process_definition_code=_opt_int(entry.get("processDefinitionCode")),
        run_times=_opt_int(entry.get("runTimes")),
        host=_opt_str(entry.get("host")),
        start_time=_opt_str(entry.get("startTime")),
        end_time=_opt_str(entry.get("endTime")),
        duration=_opt_int(entry.get("duration")),
        executor_name=_opt_str(entry.get("executorName")),
    )


def _parse_task_instance(item: object) -> RawTaskInstance | None:
    if not isinstance(item, dict):
        return None
    entry = cast(dict[str, Any], item)
    instance_id = _opt_int(entry.get("id"))
    if instance_id is None:
        return None
    return RawTaskInstance(
        id=instance_id,
        name=_opt_str(entry.get("name")),
        task_type=_opt_str(entry.get("taskType")),
        process_instance_id=_opt_int(entry.get("processInstanceId")),
        task_code=_opt_int(entry.get("taskCode")),
        state=_opt_str(entry.get("state")),
        host=_opt_str(entry.get("host")),
        start_time=_opt_str(entry.get("startTime")),
        end_time=_opt_str(entry.get("endTime")),
        duration=_opt_int(entry.get("duration")),
        retry_times=_opt_int(entry.get("retryTimes")),
        app_link=_opt_str(entry.get("appLink")),
        log_path=_opt_str(entry.get("logPath")),
        executor_name=_opt_str(entry.get("executorName")),
    )


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _opt_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
