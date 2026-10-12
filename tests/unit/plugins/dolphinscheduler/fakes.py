"""Complete fail-loud gateway for narrowly scoped DolphinScheduler tests."""

from __future__ import annotations

from mcp_stdio.plugins.dolphinscheduler.gateway import (
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


class UnsupportedGateway:
    async def get_status(self) -> tuple[RawServer, ...]:
        raise AssertionError("Unexpected gateway operation: get_status")

    async def list_projects(self) -> tuple[RawProject, ...]:
        raise AssertionError("Unexpected gateway operation: list_projects")

    async def search_projects(
        self, *, search_val: str, page_no: int, page_size: int
    ) -> RawPage[RawProject]:
        raise AssertionError("Unexpected gateway operation: search_projects")

    async def get_project(self, *, code: int) -> RawProject:
        raise AssertionError("Unexpected gateway operation: get_project")

    async def list_workflows(self, *, project_code: int) -> tuple[RawWorkflow, ...]:
        raise AssertionError("Unexpected gateway operation: list_workflows")

    async def search_workflows(
        self, *, project_code: int, search_val: str, page_no: int, page_size: int
    ) -> RawPage[RawWorkflow]:
        raise AssertionError("Unexpected gateway operation: search_workflows")

    async def get_workflow(self, *, project_code: int, code: int) -> RawWorkflow:
        raise AssertionError("Unexpected gateway operation: get_workflow")

    async def query_nodes(
        self,
        *,
        project_code: int,
        search_task_name: str | None,
        page_no: int,
        page_size: int,
    ) -> RawPage[RawNode]:
        raise AssertionError("Unexpected gateway operation: query_nodes")

    async def get_node(self, *, project_code: int, code: int) -> RawNode:
        raise AssertionError("Unexpected gateway operation: get_node")

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
        raise AssertionError("Unexpected gateway operation: query_process_instances")

    async def get_process_instance(
        self, *, project_code: int, process_instance_id: int
    ) -> RawProcessInstance:
        raise AssertionError("Unexpected gateway operation: get_process_instance")

    async def list_task_instances_of_process(
        self, *, project_code: int, process_instance_id: int
    ) -> tuple[RawTaskInstance, ...]:
        raise AssertionError("Unexpected gateway operation: list_task_instances_of_process")

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
        raise AssertionError("Unexpected gateway operation: query_task_instances")

    async def start_workflow(
        self,
        *,
        project_code: int,
        process_definition_code: int,
        dry_run: int,
        start_node_list: str | None,
        timeout: int | None,
    ) -> RawStartResult:
        raise AssertionError("Unexpected gateway operation: start_workflow")

    async def get_task_log(
        self, *, project_code: int, task_instance_id: int, skip_line_num: int, limit: int
    ) -> RawTaskLog:
        raise AssertionError("Unexpected gateway operation: get_task_log")

    async def download_task_log(self, *, project_code: int, task_instance_id: int) -> str:
        raise AssertionError("Unexpected gateway operation: download_task_log")

    async def close(self) -> None:
        raise AssertionError("Unexpected gateway operation: close")
