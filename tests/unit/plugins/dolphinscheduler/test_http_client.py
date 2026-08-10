"""DolphinScheduler HTTP adapter mock-transport tests."""

from __future__ import annotations

from typing import cast

import httpx
import pytest

from mcp_stdio.core.errors import ErrorCategory
from mcp_stdio.plugins.dolphinscheduler.config import (
    DolphinSchedulerSecrets,
    DolphinSchedulerSettings,
)
from mcp_stdio.plugins.dolphinscheduler.gateway import (
    DolphinSchedulerGatewayError,
    RawServer,
)
from mcp_stdio.plugins.dolphinscheduler.http_client import DolphinSchedulerHttpClient


def _settings(**overrides: object) -> DolphinSchedulerSettings:
    base: dict[str, object] = {"base_url": "http://ds.example:12345/dolphinscheduler"}
    base.update(overrides)
    return DolphinSchedulerSettings.model_validate(base)


def _no_secrets() -> DolphinSchedulerSecrets:
    return DolphinSchedulerSecrets()


def _token_secrets() -> DolphinSchedulerSecrets:
    return DolphinSchedulerSecrets.model_validate({"token": "tok"})


def _adapter(
    transport: httpx.MockTransport,
    *,
    secrets: DolphinSchedulerSecrets | None = None,
    settings: DolphinSchedulerSettings | None = None,
) -> DolphinSchedulerHttpClient:
    return DolphinSchedulerHttpClient(
        settings=settings or _settings(),
        secrets=secrets or _no_secrets(),
        transport=transport,
    )


def _ok(data: object) -> httpx.Response:
    return httpx.Response(200, json={"code": 0, "msg": "success", "data": data})


def _result(code: int, msg: str = "error") -> httpx.Response:
    return httpx.Response(200, json={"code": code, "msg": msg, "data": None})


def _category(error: Exception) -> ErrorCategory:
    assert isinstance(error, DolphinSchedulerGatewayError)
    return error.tool_error.category


def _server() -> dict[str, object]:
    return {
        "id": 1,
        "host": "192.168.1.1",
        "port": 5678,
        "zkDirectory": "/dolphinscheduler/nodes/master/x",
        "resInfo": "cpuUsage: 1.2%",
        "createTime": "2024-01-01 00:00:00",
        "lastHeartbeatTime": "2024-06-01 12:00:00",
    }


async def test_healthy_result_returns_bounded_server_summaries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/dolphinscheduler/monitor/masters"
        assert request.method == "GET"
        return _ok([_server(), _server()])

    adapter = _adapter(httpx.MockTransport(handler))
    servers = await adapter.get_status()
    assert len(servers) == 2
    assert servers[0] == RawServer(
        host="192.168.1.1",
        port=5678,
        res_info="cpuUsage: 1.2%",
        last_heartbeat_time="2024-06-01 12:00:00",
    )
    await adapter.close()


async def test_empty_server_list_returns_empty_tuple() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _ok([])

    adapter = _adapter(httpx.MockTransport(handler))
    assert await adapter.get_status() == ()
    await adapter.close()


async def test_drops_unknown_and_missing_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _ok([{"host": "h", "extra": "ignored"}])

    adapter = _adapter(httpx.MockTransport(handler))
    servers = await adapter.get_status()
    assert servers == (RawServer(host="h", port=None, res_info=None, last_heartbeat_time=None),)
    await adapter.close()


async def test_token_header_applied_when_configured() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["token"] = request.headers.get("token", "")
        return _ok([])

    adapter = _adapter(httpx.MockTransport(handler), secrets=_token_secrets())
    await adapter.get_status()
    assert seen["token"] == "tok"
    await adapter.close()


async def test_no_token_header_when_unauthenticated() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["token"] = request.headers.get("token", "<absent>")
        return _ok([])

    adapter = _adapter(httpx.MockTransport(handler))
    await adapter.get_status()
    assert seen["token"] == "<absent>"
    await adapter.close()


async def test_http_401_maps_to_authentication_failed() -> None:
    adapter = _adapter(httpx.MockTransport(lambda r: httpx.Response(401)))
    with pytest.raises(DolphinSchedulerGatewayError) as exc:
        await adapter.get_status()
    assert _category(exc.value) == ErrorCategory.AUTHENTICATION_FAILED
    await adapter.close()


async def test_http_403_maps_to_permission_denied() -> None:
    adapter = _adapter(httpx.MockTransport(lambda r: httpx.Response(403)))
    with pytest.raises(DolphinSchedulerGatewayError) as exc:
        await adapter.get_status()
    assert _category(exc.value) == ErrorCategory.PERMISSION_DENIED
    await adapter.close()


async def test_http_500_maps_to_upstream_error() -> None:
    adapter = _adapter(httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(DolphinSchedulerGatewayError) as exc:
        await adapter.get_status()
    assert _category(exc.value) == ErrorCategory.UPSTREAM_ERROR
    await adapter.close()


async def test_nonzero_result_code_maps_to_upstream_error() -> None:
    adapter = _adapter(httpx.MockTransport(lambda r: _result(10045, "list masters error")))
    with pytest.raises(DolphinSchedulerGatewayError) as exc:
        await adapter.get_status()
    assert _category(exc.value) == ErrorCategory.UPSTREAM_ERROR
    await adapter.close()


async def test_connection_failure_maps_to_connection_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    adapter = _adapter(httpx.MockTransport(handler))
    with pytest.raises(DolphinSchedulerGatewayError) as exc:
        await adapter.get_status()
    assert _category(exc.value) == ErrorCategory.CONNECTION_FAILED
    await adapter.close()


async def test_timeout_maps_to_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    adapter = _adapter(httpx.MockTransport(handler))
    with pytest.raises(DolphinSchedulerGatewayError) as exc:
        await adapter.get_status()
    assert _category(exc.value) == ErrorCategory.TIMEOUT
    await adapter.close()


async def test_oversized_response_maps_to_unexpected_response() -> None:
    big = "x" * 200
    adapter = _adapter(
        httpx.MockTransport(lambda r: httpx.Response(200, text=big)),
        settings=_settings(max_response_bytes=100),
    )
    with pytest.raises(DolphinSchedulerGatewayError) as exc:
        await adapter.get_status()
    assert _category(exc.value) == ErrorCategory.UNEXPECTED_RESPONSE
    await adapter.close()


async def test_non_json_body_maps_to_unexpected_response() -> None:
    adapter = _adapter(httpx.MockTransport(lambda r: httpx.Response(200, text="not-json")))
    with pytest.raises(DolphinSchedulerGatewayError) as exc:
        await adapter.get_status()
    assert _category(exc.value) == ErrorCategory.UNEXPECTED_RESPONSE
    await adapter.close()


async def test_data_not_a_list_maps_to_unexpected_response() -> None:
    adapter = _adapter(httpx.MockTransport(lambda r: _ok({"not": "a list"})))
    with pytest.raises(DolphinSchedulerGatewayError) as exc:
        await adapter.get_status()
    assert _category(exc.value) == ErrorCategory.UNEXPECTED_RESPONSE
    await adapter.close()


async def test_close_is_idempotent_and_closes_client() -> None:
    adapter = _adapter(httpx.MockTransport(lambda r: _ok([])))
    await adapter.get_status()
    await adapter.close()
    await adapter.close()


# --------------------------------------------------------------------------- scheduling


def _page(total_list: list[object], total: int) -> httpx.Response:
    return httpx.Response(
        200,
        json={"code": 0, "msg": "success", "data": {"totalList": total_list, "total": total}},
    )


def _project(code: int, name: str) -> dict[str, object]:
    return {"code": code, "name": name, "defCount": 3, "instRunningCount": 1}


def _workflow(code: int, name: str) -> dict[str, object]:
    return {"code": code, "name": name, "version": 2, "releaseState": "ONLINE", "projectCode": 9}


def _node(code: int, name: str) -> dict[str, object]:
    return {"code": code, "name": name, "taskType": "SHELL", "version": 1}


def _process_instance(pid: int, name: str) -> dict[str, object]:
    return {
        "id": pid,
        "name": name,
        "state": "SUCCESS",
        "processDefinitionCode": 11,
        "runTimes": 1,
        "host": "w1:1234",
        "startTime": "2026-08-07 12:00:00",
        "endTime": "2026-08-07 12:01:00",
        "duration": 60,
        "executorName": "admin",
    }


def _task_instance(tid: int, name: str) -> dict[str, object]:
    return {
        "id": tid,
        "name": name,
        "taskType": "SHELL",
        "processInstanceId": 5,
        "taskCode": 21,
        "state": "SUCCESS",
        "appLink": "http://rm/proxy/application_1_1",
        "logPath": "/tmp/x.log",
    }


async def test_list_projects_parses_unpaginated_list() -> None:
    adapter = _adapter(httpx.MockTransport(lambda r: _ok([_project(1, "p1"), _project(2, "p2")])))
    projects = await adapter.list_projects()
    assert [p.code for p in projects] == [1, 2]
    assert projects[0].name == "p1"
    await adapter.close()


async def test_search_projects_returns_paged_total() -> None:
    adapter = _adapter(httpx.MockTransport(lambda r: _page([_project(7, "p7")], 42)))
    page = await adapter.search_projects(search_val="p", page_no=1, page_size=10)
    assert page.total_count == 42
    assert [p.code for p in page.items] == [7]
    await adapter.close()


async def test_get_project_parses_single_object() -> None:
    adapter = _adapter(httpx.MockTransport(lambda r: _ok(_project(9, "p9"))))
    project = await adapter.get_project(code=9)
    assert project.code == 9
    assert project.def_count == 3
    await adapter.close()


async def test_list_workflows_parses_unpaginated_list() -> None:
    adapter = _adapter(httpx.MockTransport(lambda r: _ok([_workflow(11, "wf")])))
    workflows = await adapter.list_workflows(project_code=9)
    assert workflows[0].code == 11
    assert workflows[0].release_state == "ONLINE"
    await adapter.close()


async def test_search_workflows_returns_paged_total() -> None:
    adapter = _adapter(httpx.MockTransport(lambda r: _page([_workflow(12, "wf2")], 5)))
    page = await adapter.search_workflows(project_code=9, search_val="wf", page_no=1, page_size=10)
    assert page.total_count == 5
    assert page.items[0].version == 2
    await adapter.close()


async def test_query_nodes_sends_search_task_name_when_provided() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["searchTaskName"] = request.url.params.get("searchTaskName", "<absent>")
        return _page([_node(31, "n1")], 1)

    adapter = _adapter(httpx.MockTransport(handler))
    page = await adapter.query_nodes(
        project_code=9, search_task_name="spark", page_no=1, page_size=10
    )
    assert seen["searchTaskName"] == "spark"
    assert page.items[0].task_type == "SHELL"
    await adapter.close()


async def test_query_nodes_omits_search_task_name_when_absent() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["searchTaskName"] = request.url.params.get("searchTaskName", "<absent>")
        return _page([], 0)

    adapter = _adapter(httpx.MockTransport(handler))
    await adapter.query_nodes(project_code=9, search_task_name=None, page_no=1, page_size=10)
    assert seen["searchTaskName"] == "<absent>"
    await adapter.close()


async def test_get_node_parses_single_object() -> None:
    adapter = _adapter(httpx.MockTransport(lambda r: _ok(_node(31, "n1"))))
    node = await adapter.get_node(project_code=9, code=31)
    assert node.task_type == "SHELL"
    await adapter.close()


async def test_query_process_instances_applies_filters() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["processDefineCode"] = request.url.params.get("processDefineCode", "<absent>")
        seen["searchVal"] = request.url.params.get("searchVal", "<absent>")
        seen["stateType"] = request.url.params.get("stateType", "<absent>")
        return _page([_process_instance(5, "pi")], 1)

    adapter = _adapter(httpx.MockTransport(handler))
    page = await adapter.query_process_instances(
        project_code=9,
        process_definition_code=11,
        search_val="pi",
        state_type="SUCCESS",
        start_date="2026-08-01 00:00:00",
        end_date="2026-08-07 00:00:00",
        page_no=1,
        page_size=10,
    )
    assert seen["processDefineCode"] == "11"
    assert seen["searchVal"] == "pi"
    assert seen["stateType"] == "SUCCESS"
    assert page.items[0].id == 5
    await adapter.close()


async def test_get_process_instance_parses_single_object() -> None:
    adapter = _adapter(httpx.MockTransport(lambda r: _ok(_process_instance(5, "pi"))))
    instance = await adapter.get_process_instance(project_code=9, process_instance_id=5)
    assert instance.state == "SUCCESS"
    await adapter.close()


async def test_list_task_instances_of_process_parses_unpaginated_list() -> None:
    adapter = _adapter(httpx.MockTransport(lambda r: _ok([_task_instance(77, "t1")])))
    tasks = await adapter.list_task_instances_of_process(project_code=9, process_instance_id=5)
    assert tasks[0].id == 77
    assert tasks[0].app_link == "http://rm/proxy/application_1_1"
    await adapter.close()


async def test_query_task_instances_applies_process_instance_filter() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["processInstanceId"] = request.url.params.get("processInstanceId", "<absent>")
        return _page([_task_instance(77, "t1")], 1)

    adapter = _adapter(httpx.MockTransport(handler))
    page = await adapter.query_task_instances(
        project_code=9,
        process_instance_id=5,
        search_val=None,
        task_name=None,
        state_type=None,
        start_date=None,
        end_date=None,
        page_no=1,
        page_size=10,
    )
    assert seen["processInstanceId"] == "5"
    assert page.items[0].task_code == 21
    await adapter.close()


async def test_start_workflow_posts_safe_defaults_and_parses_result() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        from urllib.parse import parse_qs

        body = request.read().decode("utf-8")
        captured["form"] = {k: v[0] for k, v in parse_qs(body).items()}
        return _ok({"processInstanceId": 5567})

    adapter = _adapter(httpx.MockTransport(handler))
    result = await adapter.start_workflow(
        project_code=9,
        process_definition_code=11,
        dry_run=0,
        start_node_list=None,
        timeout=None,
    )
    form = cast(dict[str, str], captured["form"])
    assert form["processDefinitionCode"] == "11"
    assert form["failureStrategy"] == "CONTINUE"
    assert form["warningType"] == "NONE"
    assert form["dryRun"] == "0"
    assert form["workerGroup"] == "default"
    assert result.process_instance_id == 5567
    assert result.dry_run == 0
    await adapter.close()


async def test_start_workflow_without_process_instance_id_is_null() -> None:
    adapter = _adapter(httpx.MockTransport(lambda r: _ok(None)))
    result = await adapter.start_workflow(
        project_code=9, process_definition_code=11, dry_run=1, start_node_list=None, timeout=None
    )
    assert result.process_instance_id is None
    assert result.dry_run == 1
    await adapter.close()


async def test_get_task_log_parses_lines_and_next_offset() -> None:
    adapter = _adapter(
        httpx.MockTransport(lambda r: _ok([{"lineNum": 1000, "message": "starting spark-submit"}]))
    )
    log = await adapter.get_task_log(
        project_code=9, task_instance_id=77, skip_line_num=0, limit=1000
    )
    assert log.line_num == 1000
    assert "starting spark-submit" in log.message
    await adapter.close()


async def test_get_task_log_empty_page_keeps_skip_offset() -> None:
    adapter = _adapter(httpx.MockTransport(lambda r: _ok([])))
    log = await adapter.get_task_log(
        project_code=9, task_instance_id=77, skip_line_num=500, limit=1000
    )
    assert log.line_num == 500
    assert log.message == ""
    await adapter.close()


async def test_download_task_log_returns_bounded_text() -> None:
    adapter = _adapter(
        httpx.MockTransport(lambda r: httpx.Response(200, text="log-line-1\nlog-line-2\n"))
    )
    text = await adapter.download_task_log(project_code=9, task_instance_id=77)
    assert "log-line-1" in text
    await adapter.close()


async def test_download_task_log_truncates_at_max_log_bytes() -> None:
    adapter = _adapter(
        httpx.MockTransport(lambda r: httpx.Response(200, text="x" * 200)),
        settings=_settings(max_log_bytes=10),
    )
    text = await adapter.download_task_log(project_code=9, task_instance_id=77)
    assert len(text) == 10
    await adapter.close()


async def test_scheduling_401_maps_to_authentication_failed() -> None:
    adapter = _adapter(httpx.MockTransport(lambda r: httpx.Response(401)))
    with pytest.raises(DolphinSchedulerGatewayError) as exc:
        await adapter.list_projects()
    assert _category(exc.value) == ErrorCategory.AUTHENTICATION_FAILED
    await adapter.close()


async def test_scheduling_nonzero_result_code_maps_to_upstream_error() -> None:
    adapter = _adapter(httpx.MockTransport(lambda r: _result(10045, "boom")))
    with pytest.raises(DolphinSchedulerGatewayError) as exc:
        await adapter.search_projects(search_val="x", page_no=1, page_size=10)
    assert _category(exc.value) == ErrorCategory.UPSTREAM_ERROR
    await adapter.close()


async def test_paged_endpoint_non_dict_data_maps_to_unexpected_response() -> None:
    adapter = _adapter(httpx.MockTransport(lambda r: _ok(["not", "a", "page"])))
    with pytest.raises(DolphinSchedulerGatewayError) as exc:
        await adapter.search_projects(search_val="x", page_no=1, page_size=10)
    assert _category(exc.value) == ErrorCategory.UNEXPECTED_RESPONSE
    await adapter.close()


async def test_paged_endpoint_missing_total_list_maps_to_unexpected_response() -> None:
    adapter = _adapter(httpx.MockTransport(lambda r: _ok({"total": 0})))
    with pytest.raises(DolphinSchedulerGatewayError) as exc:
        await adapter.search_workflows(project_code=9, search_val="x", page_no=1, page_size=10)
    assert _category(exc.value) == ErrorCategory.UNEXPECTED_RESPONSE
    await adapter.close()


async def test_single_object_non_dict_maps_to_unexpected_response() -> None:
    adapter = _adapter(httpx.MockTransport(lambda r: _ok([1, 2, 3])))
    with pytest.raises(DolphinSchedulerGatewayError) as exc:
        await adapter.get_project(code=9)
    assert _category(exc.value) == ErrorCategory.UNEXPECTED_RESPONSE
    await adapter.close()


async def test_token_header_sent_on_scheduling_request() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["token"] = request.headers.get("token", "<absent>")
        return _ok([_project(1, "p1")])

    adapter = _adapter(httpx.MockTransport(handler), secrets=_token_secrets())
    await adapter.list_projects()
    assert seen["token"] == "tok"
    await adapter.close()
