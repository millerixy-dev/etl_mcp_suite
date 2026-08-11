"""Opt-in DolphinScheduler integration tests for status and scheduling.

Skipped unless MCP_STDIO_DOLPHINSCHEDULER_INTEGRATION=1 is set alongside
MCP_STDIO_DOLPHINSCHEDULER_BASE_URL. When MCP_STDIO_DOLPHINSCHEDULER_TOKEN is
set it is sent as the DolphinScheduler ``token`` header. Scheduling tests add
MCP_STDIO_DOLPHINSCHEDULER_PROJECT_CODE, _PROCESS_DEFINITION_CODE, and
_TASK_INSTANCE_ID. Proxy environment variables are cleared internally because
the tests connect to an internal host directly.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.asyncio

_BASE_URL = "MCP_STDIO_DOLPHINSCHEDULER_BASE_URL"
_TOKEN = "MCP_STDIO_DOLPHINSCHEDULER_TOKEN"
_PROJECT_CODE = "MCP_STDIO_DOLPHINSCHEDULER_PROJECT_CODE"
_PROCESS_DEFINITION_CODE = "MCP_STDIO_DOLPHINSCHEDULER_PROCESS_DEFINITION_CODE"
_TASK_INSTANCE_ID = "MCP_STDIO_DOLPHINSCHEDULER_TASK_INSTANCE_ID"

_REQUIRED = ("MCP_STDIO_DOLPHINSCHEDULER_INTEGRATION", _BASE_URL)


def _is_enabled() -> bool:
    return (
        all(os.environ.get(var) for var in _REQUIRED)
        and os.environ.get("MCP_STDIO_DOLPHINSCHEDULER_INTEGRATION") == "1"
    )


def _has(*variables: str) -> bool:
    return all(os.environ.get(var) for var in variables)


_PROXY_VARS = (
    "ALL_PROXY",
    "all_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
    "NO_PROXY",
    "no_proxy",
)

pytestmark = pytest.mark.skipif(
    not _is_enabled(),
    reason="set MCP_STDIO_DOLPHINSCHEDULER_INTEGRATION=1 with base_url to run",
)


@pytest.fixture(autouse=True)
def _clear_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear proxy env vars so httpx connects to the internal host directly."""
    for var in _PROXY_VARS:
        monkeypatch.delenv(var, raising=False)


def _build_service():
    from mcp_stdio.plugins.dolphinscheduler.config import (
        DolphinSchedulerSecrets,
        DolphinSchedulerSettings,
    )
    from mcp_stdio.plugins.dolphinscheduler.http_client import DolphinSchedulerHttpClient
    from mcp_stdio.plugins.dolphinscheduler.service import DolphinSchedulerStatusService

    settings = DolphinSchedulerSettings(
        base_url=os.environ[_BASE_URL],
        request_timeout_seconds=60,
    )
    token = os.environ.get(_TOKEN)
    secrets = DolphinSchedulerSecrets.model_validate({"token": token} if token else {})
    gateway = DolphinSchedulerHttpClient(settings=settings, secrets=secrets)
    service = DolphinSchedulerStatusService(
        gateway=gateway,
        max_detail_items=settings.max_detail_items,
        default_page_size=settings.default_page_size,
        max_page_size=settings.max_page_size,
        max_log_bytes=settings.max_log_bytes,
    )
    return service, gateway, token


def _assert_no_secret_leak(rendered: list[str], token: str | None) -> None:
    if token:
        for text in rendered:
            assert token not in text


async def test_status_endpoint_returns_safe_result_or_categorized_error() -> None:
    from mcp_stdio.plugins.dolphinscheduler.gateway import DolphinSchedulerGatewayError
    from mcp_stdio.plugins.dolphinscheduler.service import ServerStatusResult

    service, gateway, token = _build_service()
    rendered: list[str] = []
    try:
        result = await service.get_server_status()
        rendered.append(repr(result))
        assert isinstance(result, ServerStatusResult)
        assert result.available is True
        assert result.status in ("HEALTHY", "UNHEALTHY")
        assert result.server_count == len(result.servers)
    except DolphinSchedulerGatewayError as error:
        rendered.append(repr(error))
        rendered.append(repr(error.tool_error))
        assert error.tool_error.category is not None
    finally:
        await gateway.close()
    _assert_no_secret_leak(rendered, token)


@pytest.mark.skipif(not _has(_PROJECT_CODE), reason="requires project code")
async def test_list_and_get_objects_return_safe_result_or_categorized_error() -> None:
    from mcp_stdio.plugins.dolphinscheduler.gateway import DolphinSchedulerGatewayError
    from mcp_stdio.plugins.dolphinscheduler.service import GetObjectResult, ListObjectsResult

    service, gateway, token = _build_service()
    project_code = int(os.environ[_PROJECT_CODE])
    rendered: list[str] = []
    try:
        listed = await service.list_objects(object_type="project")
        rendered.append(repr(listed))
        assert isinstance(listed, ListObjectsResult)
        workflows = await service.list_objects(object_type="workflow", project_code=project_code)
        rendered.append(repr(workflows))
        assert isinstance(workflows, ListObjectsResult)
        if workflows.items:
            got = await service.get_object(
                object_type="workflow", project_code=project_code, code=workflows.items[0].code
            )
            rendered.append(repr(got))
            assert isinstance(got, GetObjectResult)
    except DolphinSchedulerGatewayError as error:
        rendered.append(repr(error))
        assert error.tool_error.category is not None
    finally:
        await gateway.close()
    _assert_no_secret_leak(rendered, token)


@pytest.mark.skipif(not _has(_PROJECT_CODE), reason="requires project code")
async def test_search_objects_returns_safe_result_or_categorized_error() -> None:
    from mcp_stdio.plugins.dolphinscheduler.gateway import DolphinSchedulerGatewayError
    from mcp_stdio.plugins.dolphinscheduler.service import ListObjectsResult

    service, gateway, token = _build_service()
    rendered: list[str] = []
    try:
        result = await service.search_objects(object_type="project", search_val="e")
        rendered.append(repr(result))
        assert isinstance(result, ListObjectsResult)
    except DolphinSchedulerGatewayError as error:
        rendered.append(repr(error))
        assert error.tool_error.category is not None
    finally:
        await gateway.close()
    _assert_no_secret_leak(rendered, token)


@pytest.mark.skipif(
    not _has(_PROJECT_CODE, _PROCESS_DEFINITION_CODE),
    reason="requires project and process definition codes",
)
async def test_start_workflow_dry_run_returns_safe_result_or_categorized_error() -> None:
    from mcp_stdio.plugins.dolphinscheduler.gateway import DolphinSchedulerGatewayError
    from mcp_stdio.plugins.dolphinscheduler.service import StartWorkflowResult

    service, gateway, token = _build_service()
    rendered: list[str] = []
    try:
        result = await service.start_workflow(
            project_code=int(os.environ[_PROJECT_CODE]),
            process_definition_code=int(os.environ[_PROCESS_DEFINITION_CODE]),
            dry_run=1,
        )
        rendered.append(repr(result))
        assert isinstance(result, StartWorkflowResult)
        assert result.dry_run == 1
    except DolphinSchedulerGatewayError as error:
        rendered.append(repr(error))
        assert error.tool_error.category is not None
    finally:
        await gateway.close()
    _assert_no_secret_leak(rendered, token)


@pytest.mark.skipif(not _has(_TASK_INSTANCE_ID), reason="requires task instance id")
async def test_get_task_log_returns_safe_result_or_categorized_error() -> None:
    from mcp_stdio.plugins.dolphinscheduler.gateway import DolphinSchedulerGatewayError
    from mcp_stdio.plugins.dolphinscheduler.service import GetTaskLogResult

    service, gateway, token = _build_service()
    rendered: list[str] = []
    try:
        result = await service.get_task_log(
            project_code=int(os.environ[_PROJECT_CODE]),
            task_instance_id=int(os.environ[_TASK_INSTANCE_ID]),
        )
        rendered.append(repr(result))
        assert isinstance(result, GetTaskLogResult)
        assert result.task_instance_id == int(os.environ[_TASK_INSTANCE_ID])
    except DolphinSchedulerGatewayError as error:
        rendered.append(repr(error))
        assert error.tool_error.category is not None
    finally:
        await gateway.close()
    _assert_no_secret_leak(rendered, token)


@pytest.mark.skipif(not _has(_TASK_INSTANCE_ID), reason="requires task instance id")
async def test_extract_log_links_returns_safe_result_or_categorized_error() -> None:
    from mcp_stdio.plugins.dolphinscheduler.gateway import DolphinSchedulerGatewayError
    from mcp_stdio.plugins.dolphinscheduler.service import ExtractLogLinksResult

    service, gateway, token = _build_service()
    rendered: list[str] = []
    try:
        result = await service.extract_log_links(
            project_code=int(os.environ[_PROJECT_CODE]),
            task_instance_id=int(os.environ[_TASK_INSTANCE_ID]),
        )
        rendered.append(repr(result))
        assert isinstance(result, ExtractLogLinksResult)
        assert result.task_instance_id == int(os.environ[_TASK_INSTANCE_ID])
    except DolphinSchedulerGatewayError as error:
        rendered.append(repr(error))
        assert error.tool_error.category is not None
    finally:
        await gateway.close()
    _assert_no_secret_leak(rendered, token)
