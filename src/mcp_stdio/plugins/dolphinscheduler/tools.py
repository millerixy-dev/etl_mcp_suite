"""Inbound MCP tool adapters for the DolphinScheduler surface."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import NoReturn

from mcp.server.fastmcp.exceptions import ToolError as FastMCPToolError

from mcp_stdio.contracts.plugin import ToolRegistrar
from mcp_stdio.core.errors import ToolError, ToolOperation, unexpected_tool_error
from mcp_stdio.plugins.dolphinscheduler.gateway import DolphinSchedulerGatewayError
from mcp_stdio.plugins.dolphinscheduler.service import (
    DolphinSchedulerStatusService,
    ExtractLogLinksResult,
    GetObjectResult,
    GetTaskLogResult,
    ListObjectsResult,
    ServerStatusResult,
    StartWorkflowResult,
)


class DolphinSchedulerToolAdapter:
    """Translate inbound DolphinScheduler calls to the application service."""

    def __init__(
        self,
        *,
        service: DolphinSchedulerStatusService,
        secret_values: Iterable[str],
    ) -> None:
        self._service = service
        self._secret_values = tuple(value for value in secret_values if value)

    def register_tools(self, registrar: ToolRegistrar) -> None:
        """Register exactly the approved DolphinScheduler tool set."""

        registrar.add_tool(self.get_server_status, name="get_server_status")
        registrar.add_tool(self.list_objects, name="list_objects")
        registrar.add_tool(self.get_object, name="get_object")
        registrar.add_tool(self.search_objects, name="search_objects")
        registrar.add_tool(self.start_workflow, name="start_workflow")
        registrar.add_tool(self.get_task_log, name="get_task_log")
        registrar.add_tool(self.extract_log_links, name="extract_log_links")

    async def get_server_status(self) -> ServerStatusResult:
        """Return the normalized DolphinScheduler server status."""

        try:
            return await self._service.get_server_status()
        except DolphinSchedulerGatewayError as error:
            self._raise_tool_error(error.tool_error)
        except Exception as error:
            self._raise_tool_error(
                unexpected_tool_error(error, operation=ToolOperation.GET_SERVER_STATUS)
            )

    async def list_objects(
        self,
        object_type: str,
        project_code: int | None = None,
        process_definition_code: int | None = None,
        process_instance_id: int | None = None,
        page_no: int = 1,
        page_size: int | None = None,
    ) -> ListObjectsResult:
        """Enumerate DolphinScheduler scheduling objects of the requested type.

        `object_type` is one of project, workflow, node, process_instance, or
        task_instance. `project_code` is required for every type except project.
        """

        try:
            return await self._service.list_objects(
                object_type=object_type,
                project_code=project_code,
                process_definition_code=process_definition_code,
                process_instance_id=process_instance_id,
                page_no=page_no,
                page_size=page_size,
            )
        except DolphinSchedulerGatewayError as error:
            self._raise_tool_error(error.tool_error)
        except Exception as error:
            self._raise_tool_error(
                unexpected_tool_error(error, operation=ToolOperation.LIST_OBJECTS)
            )

    async def get_object(
        self,
        object_type: str,
        project_code: int | None = None,
        code: int | None = None,
        id: int | None = None,
        process_instance_id: int | None = None,
        task_instance_id: int | None = None,
    ) -> GetObjectResult:
        """Return one DolphinScheduler object's attributes and related instances.

        Definitions (project, workflow, node) are addressed by `code`; instances
        by `id`. `task_instance` requires `process_instance_id` and
        `task_instance_id`.
        """

        try:
            return await self._service.get_object(
                object_type=object_type,
                project_code=project_code,
                code=code,
                id=id,
                process_instance_id=process_instance_id,
                task_instance_id=task_instance_id,
            )
        except DolphinSchedulerGatewayError as error:
            self._raise_tool_error(error.tool_error)
        except Exception as error:
            self._raise_tool_error(unexpected_tool_error(error, operation=ToolOperation.GET_OBJECT))

    async def search_objects(
        self,
        object_type: str,
        search_val: str,
        project_code: int | None = None,
        state_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        page_no: int = 1,
        page_size: int | None = None,
    ) -> ListObjectsResult:
        """Keyword-search DolphinScheduler scheduling objects.

        For instances, optional `state_type`, `start_date`, and `end_date`
        filters apply. `project_code` is required for every type except project.
        """

        try:
            return await self._service.search_objects(
                object_type=object_type,
                project_code=project_code,
                search_val=search_val,
                state_type=state_type,
                start_date=start_date,
                end_date=end_date,
                page_no=page_no,
                page_size=page_size,
            )
        except DolphinSchedulerGatewayError as error:
            self._raise_tool_error(error.tool_error)
        except Exception as error:
            self._raise_tool_error(
                unexpected_tool_error(error, operation=ToolOperation.SEARCH_OBJECTS)
            )

    async def start_workflow(
        self,
        project_code: int,
        process_definition_code: int,
        dry_run: int = 0,
        start_node_list: str | None = None,
        timeout: int | None = None,
    ) -> StartWorkflowResult:
        """Start a DolphinScheduler process instance from a definition code.

        `dry_run` defaults to 0 (actual execution); 1 validates without executing.
        """

        try:
            return await self._service.start_workflow(
                project_code=project_code,
                process_definition_code=process_definition_code,
                dry_run=dry_run,
                start_node_list=start_node_list,
                timeout=timeout,
            )
        except DolphinSchedulerGatewayError as error:
            self._raise_tool_error(error.tool_error)
        except Exception as error:
            self._raise_tool_error(
                unexpected_tool_error(error, operation=ToolOperation.START_WORKFLOW)
            )

    async def get_task_log(
        self,
        project_code: int,
        task_instance_id: int,
        skip_line_num: int = 0,
        limit: int | None = None,
    ) -> GetTaskLogResult:
        """Read one bounded page of a task instance's execution log.

        Pass `skip_line_num` equal to a previous result's `line_num` to page
        through the rest of the log.
        """

        try:
            return await self._service.get_task_log(
                project_code=project_code,
                task_instance_id=task_instance_id,
                skip_line_num=skip_line_num,
                limit=limit,
            )
        except DolphinSchedulerGatewayError as error:
            self._raise_tool_error(error.tool_error)
        except Exception as error:
            self._raise_tool_error(
                unexpected_tool_error(error, operation=ToolOperation.GET_TASK_LOG)
            )

    async def extract_log_links(
        self,
        project_code: int,
        task_instance_id: int,
    ) -> ExtractLogLinksResult:
        """Extract YARN application IDs and Spark UI URLs from a task log.

        No raw log text is returned.
        """

        try:
            return await self._service.extract_log_links(
                project_code=project_code,
                task_instance_id=task_instance_id,
            )
        except DolphinSchedulerGatewayError as error:
            self._raise_tool_error(error.tool_error)
        except Exception as error:
            self._raise_tool_error(
                unexpected_tool_error(error, operation=ToolOperation.EXTRACT_LOG_LINKS)
            )

    def _raise_tool_error(self, error: ToolError) -> NoReturn:
        payload = error.to_dict(secret_values=self._secret_values)
        serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        raise FastMCPToolError(serialized)
