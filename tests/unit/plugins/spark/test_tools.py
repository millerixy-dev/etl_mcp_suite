"""MCP schema and safe Spark boundary tests."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from mcp_stdio.core.server import StdioMcpServer
from mcp_stdio.plugins.spark.service import SparkEventLogService
from tests.unit.plugins.spark.test_service import FakeGateway, result


def _tools():
    from mcp_stdio.plugins.spark.tools import SparkToolAdapter

    return SparkToolAdapter(
        service=SparkEventLogService(gateway=FakeGateway(hit=True), request_timeout_seconds=2),
        secret_values=("synthetic-cookie",),
    )


async def test_tool_result_and_error_serialization() -> None:
    tools = _tools()
    value = await tools.fetch_spark_event_log("application_1_42", "1")
    assert value == result(True)
    with pytest.raises(ToolError) as error:
        await tools.fetch_spark_event_log("bad")
    assert json.loads(str(error.value))["category"] == "INVALID_INPUT"
    assert "synthetic-cookie" not in str(error.value)


async def test_strict_mcp_schema_and_unknown_parameters(tmp_path: Path) -> None:
    from mcp_stdio.plugins.spark.plugin import PLUGIN_DEFINITION

    runtime = PLUGIN_DEFINITION.create_runtime(
        None,
        environ={
            "SPARK_HISTORY_SERVER_URL": "https://history.example",
            "SPARK_CACHE_DIR": str(tmp_path),
        },
    )
    server = StdioMcpServer(runtime)
    try:
        tools = await server._fastmcp.list_tools()
        assert [tool.name for tool in tools] == [
            "fetch_spark_event_log",
            "inspect_spark_event_log",
            "query_spark_events",
            "get_spark_stage_metrics",
            "get_spark_task_distribution",
            "fetch_spark_executor_log",
        ]
        schema = tools[0].inputSchema
        assert set(schema["properties"]) == {"application_id", "attempt_id", "refresh"}
        assert schema["required"] == ["application_id"]
        assert schema["additionalProperties"] is False
        for arguments in [
            {"application_id": "application_1_42", "cookie": "forbidden-secret"},
            {"application_id": "application_1_42", "refresh": "true"},
        ]:
            with pytest.raises(ToolError) as error:
                await server._fastmcp.call_tool("fetch_spark_event_log", arguments)
            assert "forbidden-secret" not in str(error.value)
            assert "INVALID_INPUT" in str(error.value)
    finally:
        await runtime.close()


@pytest.mark.parametrize("attempt", ["null", "1", None])
async def test_nullable_attempt_preserves_literal_string(attempt: str | None) -> None:
    from mcp_stdio.plugins.spark.plugin import SparkRuntime
    from mcp_stdio.plugins.spark.tools import SparkToolAdapter

    gateway = FakeGateway()
    service = SparkEventLogService(gateway=gateway, request_timeout_seconds=2)
    server = StdioMcpServer(
        SparkRuntime(SparkToolAdapter(service=service, secret_values=()), gateway, ())
    )
    await server._fastmcp.call_tool(
        "fetch_spark_event_log", {"application_id": "application_1_42", "attempt_id": attempt}
    )
    assert gateway.calls[0][2] == attempt
    assert gateway.calls[-1][2] == attempt


async def test_inspection_schemas_strict_inputs_and_safe_operations(tmp_path: Path) -> None:
    from mcp_stdio.plugins.spark.plugin import PLUGIN_DEFINITION

    runtime = PLUGIN_DEFINITION.create_runtime(
        None,
        environ={
            "SPARK_HISTORY_SERVER_URL": "https://history.example",
            "SPARK_CACHE_DIR": str(tmp_path),
        },
    )
    server = StdioMcpServer(runtime)
    try:
        listed = {tool.name: tool for tool in await server._fastmcp.list_tools()}
        inspect = listed["inspect_spark_event_log"].inputSchema
        query = listed["query_spark_events"].inputSchema
        assert set(inspect["properties"]) == {"manifest_path", "attempt_id"}
        assert set(inspect["required"]) == {"manifest_path", "attempt_id"}
        assert set(query["required"]) == {"manifest_path", "attempt_id", "expected_sha256"}
        assert set(query["properties"]) == {
            "manifest_path",
            "attempt_id",
            "expected_sha256",
            "event_types",
            "execution_id",
            "job_id",
            "stage_id",
            "stage_attempt_id",
            "task_id",
            "executor_id",
            "task_end_reason",
            "lines",
            "after_line",
            "limit",
            "max_detail_chars",
        }
        assert inspect["additionalProperties"] is query["additionalProperties"] is False
        common = {
            "manifest_path": "/l3/manifest.json",
            "attempt_id": None,
            "expected_sha256": "a" * 64,
        }
        invalid: list[dict[str, object]] = [
            {"job_id": True},
            {"job_id": "1"},
            {"lines": [True]},
            {"event_types": []},
            {"stage_attempt_id": 1},
            {"max_detail_chars": 2049},
            {"unknown": "forbidden-secret"},
        ]
        for extra in invalid:
            with pytest.raises(ToolError) as error:
                await server._fastmcp.call_tool("query_spark_events", {**common, **extra})
            serialized = str(error.value)
            assert "INVALID_INPUT" in serialized and "query_spark_events" in serialized
            assert "forbidden-secret" not in serialized and "/l3/manifest.json" not in serialized
        with pytest.raises(ToolError) as error:
            await server._fastmcp.call_tool(
                "inspect_spark_event_log", {"manifest_path": "/l3/manifest.json"}
            )
        assert "inspect_spark_event_log" in str(error.value)
    finally:
        await runtime.close()


async def test_metrics_schemas_and_strict_inputs(tmp_path: Path) -> None:
    from mcp_stdio.plugins.spark.plugin import PLUGIN_DEFINITION

    runtime = PLUGIN_DEFINITION.create_runtime(
        None,
        environ={
            "SPARK_HISTORY_SERVER_URL": "https://history.example",
            "SPARK_CACHE_DIR": str(tmp_path),
        },
    )
    server = StdioMcpServer(runtime)
    common = {"manifest_path": "/l3/manifest.json", "attempt_id": None, "expected_sha256": "a" * 64}
    try:
        listed = {tool.name: tool for tool in await server._fastmcp.list_tools()}
        for name in ["get_spark_stage_metrics", "get_spark_task_distribution"]:
            schema = listed[name].inputSchema
            required = {"manifest_path", "attempt_id", "expected_sha256"}
            properties = required | {"stage_id", "stage_attempt_id", "limit"}
            if name == "get_spark_task_distribution":
                required |= {"stage_id", "stage_attempt_id"}
                properties |= {"order_by"}
                assert schema["properties"]["order_by"]["enum"] == [
                    "duration_ms",
                    "executor_run_time_ms",
                    "jvm_gc_time_ms",
                    "input_bytes",
                    "shuffle_read_bytes",
                    "shuffle_fetch_wait_ms",
                ]
                assert schema["properties"]["order_by"]["default"] == "duration_ms"
            assert set(schema["required"]) == required
            assert set(schema["properties"]) == properties
            assert schema["additionalProperties"] is False
            assert schema["properties"]["limit"]["default"] == 20
            valid = {**common, "stage_id": 1, "stage_attempt_id": 0}
            for extra in [
                {"stage_id": True},
                {"stage_id": "1"},
                {"limit": 0},
                {"limit": 21},
                {"unknown": "forbidden-secret"},
                {"attempt_id": "../1"},
                {"expected_sha256": "bad"},
            ]:
                with pytest.raises(ToolError) as error:
                    await server._fastmcp.call_tool(name, {**valid, **extra})
                assert "INVALID_INPUT" in str(error.value) and name in str(error.value)
                assert "forbidden-secret" not in str(error.value)
            missing_attempt = {key: value for key, value in valid.items() if key != "attempt_id"}
            with pytest.raises(ToolError):
                await server._fastmcp.call_tool(name, missing_attempt)
        with pytest.raises(ToolError) as error:
            await server._fastmcp.call_tool("get_spark_stage_metrics", {**common, "stage_id": 1})
        assert "INVALID_INPUT" in str(error.value)
        with pytest.raises(ToolError) as error:
            await server._fastmcp.call_tool(
                "get_spark_task_distribution",
                {**common, "stage_id": 1, "stage_attempt_id": 0, "order_by": "average"},
            )
        assert "INVALID_INPUT" in str(error.value)
    finally:
        await runtime.close()


@pytest.mark.parametrize("name", ["get_spark_stage_metrics", "get_spark_task_distribution"])
async def test_metrics_public_boundary_redacts_and_revalidates_named_results(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock

    from mcp_stdio.plugins.spark.service import SparkMetricsService
    from mcp_stdio.plugins.spark.tools import SparkToolAdapter
    from tests.unit.plugins.spark.test_service import (
        SuccessfulMetricsGateway,
        distribution_result,
        stage_result,
    )

    gateway = SuccessfulMetricsGateway()
    service = SparkMetricsService(gateway=gateway, request_timeout_seconds=2)
    method = "stage_metrics" if name == "get_spark_stage_metrics" else "task_distribution"
    internal = stage_result() if method == "stage_metrics" else distribution_result()
    selected = {"stage_id": 1, "stage_attempt_id": 0}
    monkeypatch.setattr(service, method, AsyncMock(return_value=internal))
    adapter = SparkToolAdapter(
        service=SparkEventLogService(gateway=FakeGateway(), request_timeout_seconds=2),
        metrics_service=service,
        secret_values=(),
    )
    public = await getattr(adapter, name)("/l3/manifest.json", None, "a" * 64, **selected)
    assert public == internal and public is not internal
    assert public.model_dump() == internal.model_dump()
    blocked = SparkToolAdapter(
        service=SparkEventLogService(gateway=FakeGateway(), request_timeout_seconds=2),
        metrics_service=service,
        secret_values=("application_1_42",),
    )
    with pytest.raises(ToolError) as error:
        await getattr(blocked, name)("/l3/manifest.json", None, "a" * 64, **selected)
    assert "UNEXPECTED_RESPONSE" in str(error.value) and name in str(error.value)
    assert "application_1_42" not in str(error.value)
    assert internal.snapshot.application_id == "application_1_42"
    if method == "task_distribution":
        payload = distribution_result().model_dump()
        payload["top_tasks"] = (
            {
                "task_id": 1,
                "executor_id": "synthetic-current",
                "ref": {"sha256": "a" * 64, "line": 1},
                "duration_ms": 1,
                "executor_run_time_ms": None,
                "jvm_gc_time_ms": None,
                "input_bytes": None,
                "shuffle_read_bytes": None,
                "shuffle_fetch_wait_ms": None,
            },
        )
        internal = type(internal).model_validate(payload)
        monkeypatch.setattr(service, method, AsyncMock(return_value=internal))
        executor_blocked = SparkToolAdapter(
            service=SparkEventLogService(gateway=FakeGateway(), request_timeout_seconds=2),
            metrics_service=service,
            secret_values=("synthetic-current",),
        )
        with pytest.raises(ToolError) as error:
            await executor_blocked.get_spark_task_distribution(
                "/l3/manifest.json", None, "a" * 64, 1, 0
            )
        assert "UNEXPECTED_RESPONSE" in str(error.value)
        assert "synthetic-current" not in str(error.value)
    monkeypatch.setattr(service, method, AsyncMock(return_value=result(True)))
    with pytest.raises(ToolError) as error:
        await getattr(adapter, name)("/l3/manifest.json", None, "a" * 64, **selected)
    assert "UNEXPECTED_RESPONSE" in str(error.value) and name in str(error.value)


async def test_full_result_redaction_preserves_raw_counting_labels(tmp_path: Path) -> None:
    import hashlib
    import time

    from mcp_stdio.plugins.spark.config import SparkSettings
    from mcp_stdio.plugins.spark.inspection import SparkInspectionAdapter
    from mcp_stdio.plugins.spark.service import SparkInspectionService
    from mcp_stdio.plugins.spark.tools import SparkToolAdapter
    from tests.unit.plugins.spark.fixtures import encode, events, private_manifest

    manifest, body = private_manifest(tmp_path, ("1",))
    records = events("1") + [
        {"Event": "vendor.password=synthetic", "Description": "secret-current"},
        {
            "Event": "SparkListenerTaskEnd",
            "Task End Reason": {"Reason": "vendor password=synthetic"},
        },
    ]
    raw = encode(records)
    file = body["files"][0]
    Path(file["local_path"]).write_bytes(raw)  # noqa: ASYNC240 - bounded synthetic fixture
    file.update(
        size_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), event_count=len(records)
    )
    manifest.write_text(json.dumps(body))
    gateway = SparkInspectionAdapter(
        SparkSettings(history_server_url="https://history.example", cache_dir=str(tmp_path))
    )
    inspection = SparkInspectionService(gateway=gateway, request_timeout_seconds=2)
    from mcp_stdio.plugins.spark.inspection_models import InspectRequest

    internal = await gateway.inspect(
        InspectRequest(manifest_path=str(manifest), attempt_id="1"),
        deadline=time.monotonic() + 2,
    )
    assert internal.task_end_reasons[0].reason == "vendor password=synthetic"
    adapter = SparkToolAdapter(
        service=SparkEventLogService(gateway=FakeGateway(), request_timeout_seconds=2),
        inspection_service=inspection,
        secret_values=("secret-current",),
    )
    try:
        overview = await adapter.inspect_spark_event_log(str(manifest), "1")
        selected = await adapter.query_spark_events(
            str(manifest), "1", file["sha256"], task_end_reason="vendor password=synthetic"
        )
        assert selected.matched_count == 1
        vendor = await adapter.query_spark_events(
            str(manifest), "1", file["sha256"], lines=[4], limit=1
        )
        assert vendor.returned_count == 1
        assert "[REDACTED]" in vendor.events[0].details
        for value in (overview, selected, vendor):
            assert "synthetic" not in value.model_dump_json()
            assert "secret-current" not in value.model_dump_json()
        assert internal.task_end_reasons[0].reason == "vendor password=synthetic"
        blocked = SparkToolAdapter(
            service=SparkEventLogService(gateway=FakeGateway(), request_timeout_seconds=2),
            inspection_service=inspection,
            secret_values=("application_1_42",),
        )
        with pytest.raises(ToolError) as error:
            await blocked.inspect_spark_event_log(str(manifest), "1")
        assert "UNEXPECTED_RESPONSE" in str(error.value)
    finally:
        await gateway.close()


async def test_executor_log_schema_and_disabled_safe_error(tmp_path: Path) -> None:
    from mcp_stdio.plugins.spark.plugin import PLUGIN_DEFINITION

    runtime = PLUGIN_DEFINITION.create_runtime(
        None,
        environ={
            "SPARK_HISTORY_SERVER_URL": "https://history.example",
            "SPARK_CACHE_DIR": str(tmp_path),
        },
    )
    server = StdioMcpServer(runtime)
    try:
        listed = {tool.name: tool for tool in await server._fastmcp.list_tools()}
        schema = listed["fetch_spark_executor_log"].inputSchema
        assert set(schema["properties"]) == {
            "application_id",
            "attempt_id",
            "executor_id",
            "log_type",
            "tail_bytes",
        }
        assert schema["required"] == ["application_id", "attempt_id", "executor_id"]
        assert schema["additionalProperties"] is False
        common = {"application_id": "application_1_42", "attempt_id": "2", "executor_id": "driver"}
        for extra in (
            {"attempt_id": None},
            {"tail_bytes": True},
            {"tail_bytes": "1"},
            {"log_type": "syslog"},
            {"url": "forbidden-secret"},
        ):
            with pytest.raises(ToolError) as error:
                await server._fastmcp.call_tool("fetch_spark_executor_log", {**common, **extra})
            value = json.loads(str(error.value))
            assert value["category"] == "INVALID_INPUT"
            assert value["operation"] == "fetch_spark_executor_log"
            assert "forbidden-secret" not in str(error.value)
        with pytest.raises(ToolError) as error:
            await server._fastmcp.call_tool("fetch_spark_executor_log", common)
        assert '"category":"CONFIG_ERROR"' in str(error.value)
    finally:
        await runtime.close()
