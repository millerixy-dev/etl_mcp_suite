"""DolphinScheduler status service unit tests with a fake gateway."""

from __future__ import annotations

import pytest

from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation
from mcp_stdio.plugins.dolphinscheduler.gateway import (
    DolphinSchedulerGateway,
    DolphinSchedulerGatewayError,
    RawServer,
)
from mcp_stdio.plugins.dolphinscheduler.service import (
    DolphinSchedulerStatusService,
    ServerStatusResult,
)


class FakeGateway:
    def __init__(self, servers: tuple[RawServer, ...] = (), error: Exception | None = None) -> None:
        self._servers = servers
        self._error = error

    async def get_status(self) -> tuple[RawServer, ...]:
        if self._error is not None:
            raise self._error
        return self._servers

    async def close(self) -> None:
        return None


def _server(host: str) -> RawServer:
    return RawServer(host=host, port=5678, res_info="cpu", last_heartbeat_time="t")


def _service(
    max_detail_items: int = 100,
    gateway: DolphinSchedulerGateway | None = None,
) -> DolphinSchedulerStatusService:
    return DolphinSchedulerStatusService(
        gateway=gateway or FakeGateway(),
        max_detail_items=max_detail_items,
    )


async def test_nonempty_servers_are_healthy() -> None:
    service = _service(gateway=FakeGateway((_server("h1"), _server("h2"))))
    result = await service.get_server_status()
    assert result == ServerStatusResult(
        available=True,
        status="HEALTHY",
        server_count=2,
        servers=result.servers,
    )
    assert result.servers[0].host == "h1"
    assert result.servers[1].host == "h2"


async def test_empty_servers_are_unhealthy() -> None:
    service = _service(gateway=FakeGateway(()))
    result = await service.get_server_status()
    assert result.available is True
    assert result.status == "UNHEALTHY"
    assert result.server_count == 0
    assert result.servers == ()


async def test_detail_is_bounded_at_max_detail_items() -> None:
    many = tuple(_server(f"h{i}") for i in range(150))
    service = _service(max_detail_items=100, gateway=FakeGateway(many))
    result = await service.get_server_status()
    assert result.server_count == 100
    assert len(result.servers) == 100
    assert result.servers[0].host == "h0"
    assert result.servers[99].host == "h99"


async def test_gateway_error_propagates() -> None:
    error = DolphinSchedulerGatewayError(
        ToolError.create(
            category=ErrorCategory.AUTHENTICATION_FAILED,
            operation=ToolOperation.GET_SERVER_STATUS,
            retryable=False,
            identifiers={},
        )
    )
    service = _service(gateway=FakeGateway(error=error))
    with pytest.raises(DolphinSchedulerGatewayError) as exc:
        await service.get_server_status()
    assert exc.value.tool_error.category == ErrorCategory.AUTHENTICATION_FAILED


# --------------------------------------------------------------------------- scheduling


from mcp_stdio.plugins.dolphinscheduler.gateway import (  # noqa: E402
    RawNode,
    RawPage,
    RawProcessInstance,
    RawProject,
    RawStartResult,
    RawTaskInstance,
    RawTaskLog,
    RawWorkflow,
)


class SchedulingGateway:
    """Fake gateway recording calls and returning canned scheduling values."""

    def __init__(self) -> None:
        self.projects: tuple[RawProject, ...] = ()
        self.workflows: tuple[RawWorkflow, ...] = ()
        self.nodes_page: RawPage[RawNode] = RawPage((), 0)
        self.process_instances_page: RawPage[RawProcessInstance] = RawPage((), 0)
        self.task_instances_page: RawPage[RawTaskInstance] = RawPage((), 0)
        self.task_instances_of_process: tuple[RawTaskInstance, ...] = ()
        self.project = RawProject(1)
        self.workflow = RawWorkflow(11)
        self.node = RawNode(31)
        self.process_instance = RawProcessInstance(5)
        self.start_result = RawStartResult(11, None, 0)
        self.task_log = RawTaskLog(0, "")
        self.downloaded_log = ""
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def get_status(self) -> tuple[RawServer, ...]:
        return ()

    async def list_projects(self) -> tuple[RawProject, ...]:
        self.calls.append(("list_projects", {}))
        return self.projects

    async def search_projects(self, *, search_val, page_no, page_size):
        self.calls.append(
            (
                "search_projects",
                {"search_val": search_val, "page_no": page_no, "page_size": page_size},
            )
        )
        return self.projects and RawPage(self.projects, len(self.projects)) or RawPage((), 0)

    async def get_project(self, *, code):
        self.calls.append(("get_project", {"code": code}))
        return self.project

    async def list_workflows(self, *, project_code):
        self.calls.append(("list_workflows", {"project_code": project_code}))
        return self.workflows

    async def search_workflows(self, *, project_code, search_val, page_no, page_size):
        self.calls.append(("search_workflows", {"search_val": search_val, "page_size": page_size}))
        return RawPage(self.workflows, len(self.workflows))

    async def get_workflow(self, *, project_code, code):
        self.calls.append(("get_workflow", {"code": code}))
        return self.workflow

    async def query_nodes(self, *, project_code, search_task_name, page_no, page_size):
        self.calls.append(
            ("query_nodes", {"search_task_name": search_task_name, "page_size": page_size})
        )
        return self.nodes_page

    async def get_node(self, *, project_code, code):
        self.calls.append(("get_node", {"code": code}))
        return self.node

    async def query_process_instances(
        self,
        *,
        project_code,
        process_definition_code,
        search_val,
        state_type,
        start_date,
        end_date,
        page_no,
        page_size,
    ):
        self.calls.append(
            (
                "query_process_instances",
                {
                    "process_definition_code": process_definition_code,
                    "search_val": search_val,
                    "page_size": page_size,
                },
            )
        )
        return self.process_instances_page

    async def get_process_instance(self, *, project_code, process_instance_id):
        self.calls.append(("get_process_instance", {"process_instance_id": process_instance_id}))
        return self.process_instance

    async def list_task_instances_of_process(self, *, project_code, process_instance_id):
        self.calls.append(
            ("list_task_instances_of_process", {"process_instance_id": process_instance_id})
        )
        return self.task_instances_of_process

    async def query_task_instances(
        self,
        *,
        project_code,
        process_instance_id,
        search_val,
        task_name,
        state_type,
        start_date,
        end_date,
        page_no,
        page_size,
    ):
        self.calls.append(
            (
                "query_task_instances",
                {
                    "process_instance_id": process_instance_id,
                    "search_val": search_val,
                    "page_size": page_size,
                },
            )
        )
        return self.task_instances_page

    async def start_workflow(
        self, *, project_code, process_definition_code, dry_run, start_node_list, timeout
    ):
        self.calls.append(
            (
                "start_workflow",
                {"dry_run": dry_run, "start_node_list": start_node_list, "timeout": timeout},
            )
        )
        return self.start_result

    async def get_task_log(self, *, project_code, task_instance_id, skip_line_num, limit):
        self.calls.append(("get_task_log", {"skip_line_num": skip_line_num, "limit": limit}))
        return self.task_log

    async def download_task_log(self, *, project_code, task_instance_id):
        self.calls.append(("download_task_log", {"task_instance_id": task_instance_id}))
        return self.downloaded_log

    async def close(self) -> None:
        return None


def _sched(
    *,
    max_detail_items: int = 100,
    default_page_size: int = 10,
    max_page_size: int = 100,
    gateway: SchedulingGateway | None = None,
) -> tuple[DolphinSchedulerStatusService, SchedulingGateway]:
    gw = gateway or SchedulingGateway()
    return DolphinSchedulerStatusService(
        gateway=gw,
        max_detail_items=max_detail_items,
        default_page_size=default_page_size,
        max_page_size=max_page_size,
    ), gw


async def test_list_projects_unpaginated_and_bounded() -> None:
    gw = SchedulingGateway()
    gw.projects = tuple(RawProject(code=i, name=f"p{i}") for i in range(150))
    service, _ = _sched(max_detail_items=100, gateway=gw)
    result = await service.list_objects(object_type="project")
    assert result.object_type == "project"
    assert result.total_count == 150
    assert len(result.items) == 100
    assert result.truncated is True


async def test_list_workflows_uses_project_code() -> None:
    gw = SchedulingGateway()
    gw.workflows = (RawWorkflow(11, "wf"),)
    service, gw = _sched(gateway=gw)
    result = await service.list_objects(object_type="workflow", project_code=9)
    assert result.items[0].code == 11
    assert gw.calls[0] == ("list_workflows", {"project_code": 9})


async def test_list_nodes_caps_page_size_at_max() -> None:
    gw = SchedulingGateway()
    gw.nodes_page = RawPage((RawNode(31, "n"),), 1)
    service, gw = _sched(max_page_size=50, gateway=gw)
    await service.list_objects(object_type="node", project_code=9, page_size=999)
    assert gw.calls[0][1]["page_size"] == 50


async def test_list_process_instances_passes_definition_filter() -> None:
    gw = SchedulingGateway()
    gw.process_instances_page = RawPage((RawProcessInstance(5, "pi"),), 1)
    service, gw = _sched(gateway=gw)
    await service.list_objects(
        object_type="process_instance", project_code=9, process_definition_code=11
    )
    assert gw.calls[0][1]["process_definition_code"] == 11


async def test_list_task_instances_passes_process_instance_filter() -> None:
    gw = SchedulingGateway()
    gw.task_instances_page = RawPage((RawTaskInstance(77, "t"),), 1)
    service, gw = _sched(gateway=gw)
    await service.list_objects(object_type="task_instance", project_code=9, process_instance_id=5)
    assert gw.calls[0][1]["process_instance_id"] == 5


async def test_list_objects_rejects_unknown_object_type_without_network() -> None:
    service, gw = _sched()
    with pytest.raises(DolphinSchedulerGatewayError) as exc:
        await service.list_objects(object_type="cluster", project_code=9)
    assert exc.value.tool_error.category == ErrorCategory.INVALID_INPUT
    assert gw.calls == []


async def test_list_objects_rejects_missing_project_code_without_network() -> None:
    service, gw = _sched()
    with pytest.raises(DolphinSchedulerGatewayError) as exc:
        await service.list_objects(object_type="workflow")
    assert exc.value.tool_error.category == ErrorCategory.INVALID_INPUT
    assert gw.calls == []


async def test_get_workflow_returns_related_process_instances() -> None:
    gw = SchedulingGateway()
    gw.workflow = RawWorkflow(11, "wf")
    gw.process_instances_page = RawPage((RawProcessInstance(5, "pi"),), 1)
    service, _ = _sched(gateway=gw)
    result = await service.get_object(object_type="workflow", project_code=9, code=11)
    assert result.object.code == 11
    assert result.related is not None
    assert result.related[0].id == 5


async def test_get_process_instance_returns_related_task_instances() -> None:
    gw = SchedulingGateway()
    gw.process_instance = RawProcessInstance(5, "pi")
    gw.task_instances_of_process = (RawTaskInstance(77, "t"),)
    service, _ = _sched(gateway=gw)
    result = await service.get_object(object_type="process_instance", project_code=9, id=5)
    assert result.object.id == 5
    assert result.related is not None
    assert result.related[0].id == 77


async def test_get_task_instance_resolves_via_process_instance_tasks() -> None:
    gw = SchedulingGateway()
    gw.task_instances_of_process = (RawTaskInstance(76, "a"), RawTaskInstance(77, "b"))
    service, _ = _sched(gateway=gw)
    result = await service.get_object(
        object_type="task_instance", project_code=9, process_instance_id=5, task_instance_id=77
    )
    assert result.object.id == 77


async def test_get_task_instance_not_found_is_invalid_input() -> None:
    gw = SchedulingGateway()
    gw.task_instances_of_process = (RawTaskInstance(76, "a"),)
    service, _ = _sched(gateway=gw)
    with pytest.raises(DolphinSchedulerGatewayError) as exc:
        await service.get_object(
            object_type="task_instance", project_code=9, process_instance_id=5, task_instance_id=999
        )
    assert exc.value.tool_error.category == ErrorCategory.INVALID_INPUT


async def test_search_nodes_maps_keyword_to_search_task_name() -> None:
    gw = SchedulingGateway()
    gw.nodes_page = RawPage((RawNode(31, "n"),), 1)
    service, gw = _sched(gateway=gw)
    await service.search_objects(object_type="node", project_code=9, search_val="spark")
    assert gw.calls[0][1]["search_task_name"] == "spark"


async def test_search_objects_rejects_empty_keyword() -> None:
    service, gw = _sched()
    with pytest.raises(DolphinSchedulerGatewayError) as exc:
        await service.search_objects(object_type="project", search_val="   ")
    assert exc.value.tool_error.category == ErrorCategory.INVALID_INPUT
    assert gw.calls == []


async def test_start_workflow_returns_message_and_defaults() -> None:
    gw = SchedulingGateway()
    gw.start_result = RawStartResult(11, 5567, 0)
    service, _ = _sched(gateway=gw)
    result = await service.start_workflow(project_code=9, process_definition_code=11)
    assert result.process_instance_id == 5567
    assert result.message == "start process instance success"


async def test_start_workflow_dry_run_message() -> None:
    gw = SchedulingGateway()
    gw.start_result = RawStartResult(11, None, 1)
    service, _ = _sched(gateway=gw)
    result = await service.start_workflow(project_code=9, process_definition_code=11, dry_run=1)
    assert result.message == "dry run validation requested"


async def test_start_workflow_rejects_invalid_dry_run() -> None:
    service, gw = _sched()
    with pytest.raises(DolphinSchedulerGatewayError) as exc:
        await service.start_workflow(project_code=9, process_definition_code=11, dry_run=2)
    assert exc.value.tool_error.category == ErrorCategory.INVALID_INPUT
    assert gw.calls == []


async def test_get_task_log_returns_offset_and_message() -> None:
    gw = SchedulingGateway()
    gw.task_log = RawTaskLog(1000, "log text")
    service, gw = _sched(default_page_size=1000, gateway=gw)
    result = await service.get_task_log(project_code=9, task_instance_id=77, skip_line_num=0)
    assert result.line_num == 1000
    assert result.message == "log text"
    assert gw.calls[0][1]["limit"] == 1000


async def test_get_task_log_rejects_negative_skip() -> None:
    service, gw = _sched()
    with pytest.raises(DolphinSchedulerGatewayError) as exc:
        await service.get_task_log(project_code=9, task_instance_id=77, skip_line_num=-1)
    assert exc.value.tool_error.category == ErrorCategory.INVALID_INPUT
    assert gw.calls == []


async def test_extract_log_links_finds_yarn_and_spark_without_raw_log() -> None:
    gw = SchedulingGateway()
    gw.downloaded_log = (
        "submitting application_1690000000000_0001\n"
        "Spark UI: http://rm-host:8088/proxy/application_1690000000000_0001\n"
        "application_1690000000000_0001 tracking again"
    )
    service, _ = _sched(gateway=gw)
    result = await service.extract_log_links(project_code=9, task_instance_id=77)
    assert result.yarn_application_ids == ("application_1690000000000_0001",)
    assert result.spark_ui_urls == ("http://rm-host:8088/proxy/application_1690000000000_0001",)


async def test_extract_log_links_empty_when_no_matches() -> None:
    gw = SchedulingGateway()
    gw.downloaded_log = "no links here"
    service, _ = _sched(gateway=gw)
    result = await service.extract_log_links(project_code=9, task_instance_id=77)
    assert result.yarn_application_ids == ()
    assert result.spark_ui_urls == ()
