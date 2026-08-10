"""DolphinScheduler MCP tool adapter contract tests."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from mcp.server.fastmcp.exceptions import ToolError as FastMCPToolError

from mcp_stdio.bootstrap import construct_runtime, parse_args
from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation
from mcp_stdio.core.server import StdioMcpServer
from mcp_stdio.plugins.dolphinscheduler.gateway import (
    DolphinSchedulerGatewayError,
    RawServer,
)
from mcp_stdio.plugins.dolphinscheduler.service import DolphinSchedulerStatusService
from mcp_stdio.plugins.dolphinscheduler.tools import DolphinSchedulerToolAdapter


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


def _write_config(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "plugin": "dolphinscheduler",
                "settings": {"base_url": "http://ds.example:12345/dolphinscheduler"},
                "secrets": {},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_dolphinscheduler_registers_exact_tool_set(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "dolphinscheduler.json")
    args = parse_args(["--plugin", "dolphinscheduler", "--config", str(config)])
    runtime = construct_runtime(args, environ={})
    server = StdioMcpServer(runtime)

    assert sorted(server.tool_names()) == [
        "extract_log_links",
        "get_object",
        "get_server_status",
        "get_task_log",
        "list_objects",
        "search_objects",
        "start_workflow",
    ]


def test_get_server_status_takes_no_input_arguments() -> None:
    params = set(inspect.signature(DolphinSchedulerToolAdapter.get_server_status).parameters) - {
        "self"
    }
    assert params == set()


async def test_get_server_status_returns_normalized_result_shape() -> None:
    service = DolphinSchedulerStatusService(
        gateway=FakeGateway((RawServer("h", 1, "cpu", "t"),)),
        max_detail_items=100,
    )
    adapter = DolphinSchedulerToolAdapter(service=service, secret_values=())
    result = await adapter.get_server_status()

    assert result.available is True
    assert result.status == "HEALTHY"
    assert result.server_count == 1
    assert result.servers[0].host == "h"


async def test_error_serialization_is_secret_safe_and_categorized() -> None:
    secret = "super-secret-token"
    error = DolphinSchedulerGatewayError(
        ToolError.create(
            category=ErrorCategory.AUTHENTICATION_FAILED,
            operation=ToolOperation.GET_SERVER_STATUS,
            retryable=False,
            identifiers={},
        )
    )
    service = DolphinSchedulerStatusService(
        gateway=FakeGateway(error=error),
        max_detail_items=100,
    )
    adapter = DolphinSchedulerToolAdapter(service=service, secret_values=(secret,))

    with pytest.raises(FastMCPToolError) as exc_info:
        await adapter.get_server_status()

    payload = json.loads(str(exc_info.value))
    assert payload["category"] == "AUTHENTICATION_FAILED"
    assert secret not in str(exc_info.value)


# --------------------------------------------------------------------------- scheduling contracts


from mcp_stdio.plugins.dolphinscheduler.gateway import (  # noqa: E402
    RawProject,
    RawStartResult,
    RawTaskLog,
)
from mcp_stdio.plugins.dolphinscheduler.service import (  # noqa: E402
    ExtractLogLinksResult,
    GetTaskLogResult,
    ListObjectsResult,
    StartWorkflowResult,
)


def _required_params(method) -> set[str]:
    signature = inspect.signature(method)
    return {
        name
        for name, param in signature.parameters.items()
        if name != "self" and param.default is inspect.Parameter.empty
    }


def test_list_objects_input_schema() -> None:
    assert _required_params(DolphinSchedulerToolAdapter.list_objects) == {"object_type"}


def test_get_object_input_schema() -> None:
    assert _required_params(DolphinSchedulerToolAdapter.get_object) == {"object_type"}


def test_search_objects_input_schema() -> None:
    assert _required_params(DolphinSchedulerToolAdapter.search_objects) == {
        "object_type",
        "search_val",
    }


def test_start_workflow_input_schema() -> None:
    assert _required_params(DolphinSchedulerToolAdapter.start_workflow) == {
        "project_code",
        "process_definition_code",
    }


def test_get_task_log_input_schema() -> None:
    assert _required_params(DolphinSchedulerToolAdapter.get_task_log) == {
        "project_code",
        "task_instance_id",
    }


def test_extract_log_links_input_schema() -> None:
    assert _required_params(DolphinSchedulerToolAdapter.extract_log_links) == {
        "project_code",
        "task_instance_id",
    }


class StubGateway:
    async def get_status(self):
        return ()

    async def list_projects(self):
        return (RawProject(1, "p1"),)

    async def start_workflow(
        self, *, project_code, process_definition_code, dry_run, start_node_list, timeout
    ):
        return RawStartResult(process_definition_code, None, dry_run)

    async def get_task_log(self, *, project_code, task_instance_id, skip_line_num, limit):
        return RawTaskLog(1000, "log-line")

    async def download_task_log(self, *, project_code, task_instance_id):
        return "application_1690000000000_0001\nSpark UI: http://rm:8088/proxy/application_1690000000000_0001"

    async def close(self) -> None:
        return None


def _stub_adapter(secret_values: tuple[str, ...] = ()) -> DolphinSchedulerToolAdapter:
    service = DolphinSchedulerStatusService(gateway=StubGateway(), max_detail_items=100)
    return DolphinSchedulerToolAdapter(service=service, secret_values=secret_values)


async def test_list_objects_returns_normalized_result_shape() -> None:
    result = await _stub_adapter().list_objects(object_type="project")
    assert isinstance(result, ListObjectsResult)
    assert result.object_type == "project"
    assert result.items[0].code == 1
    assert result.page_no == 1


async def test_start_workflow_returns_normalized_result_shape() -> None:
    result = await _stub_adapter().start_workflow(project_code=9, process_definition_code=11)
    assert isinstance(result, StartWorkflowResult)
    assert result.process_definition_code == 11
    assert result.dry_run == 0


async def test_get_task_log_returns_normalized_result_shape() -> None:
    result = await _stub_adapter().get_task_log(project_code=9, task_instance_id=77)
    assert isinstance(result, GetTaskLogResult)
    assert result.task_instance_id == 77
    assert result.line_num == 1000


async def test_extract_log_links_returns_normalized_result_shape() -> None:
    result = await _stub_adapter().extract_log_links(project_code=9, task_instance_id=77)
    assert isinstance(result, ExtractLogLinksResult)
    assert result.yarn_application_ids == ("application_1690000000000_0001",)
    assert result.spark_ui_urls == ("http://rm:8088/proxy/application_1690000000000_0001",)


async def test_scheduling_invalid_input_serializes_secret_safe_and_categorized() -> None:
    secret = "super-secret-token"
    adapter = _stub_adapter(secret_values=(secret,))
    with pytest.raises(FastMCPToolError) as exc_info:
        await adapter.list_objects(object_type="cluster", project_code=9)
    payload = json.loads(str(exc_info.value))
    assert payload["category"] == "INVALID_INPUT"
    assert secret not in str(exc_info.value)
