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
        assert [tool.name for tool in tools] == ["fetch_spark_event_log"]
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
