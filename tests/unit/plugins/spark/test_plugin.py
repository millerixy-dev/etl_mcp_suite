"""Composition uses only local resources at startup."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from mcp_stdio.core.server import StdioMcpServer


async def test_lazy_startup_and_idempotent_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mcp_stdio.plugins.spark.plugin import PLUGIN_DEFINITION

    def reject(*args: object, **kwargs: object) -> None:
        raise AssertionError("startup network")

    monkeypatch.setattr(socket.socket, "connect", reject)
    runtime = PLUGIN_DEFINITION.create_runtime(
        None,
        environ={
            "SPARK_HISTORY_SERVER_URL": "https://unreachable.example",
            "SPARK_CACHE_DIR": str(tmp_path / "l3"),
            "SPARK_GATEWAY_COOKIE": "session=synthetic-cookie",
        },
    )
    assert runtime.name == "spark"
    assert "synthetic-cookie" in tuple(runtime.redaction_values)
    assert StdioMcpServer(runtime).tool_names() == [
        "fetch_spark_event_log",
        "inspect_spark_event_log",
        "query_spark_events",
    ]
    await runtime.close()
    await runtime.close()
    replacement = PLUGIN_DEFINITION.create_runtime(
        None,
        environ={
            "SPARK_HISTORY_SERVER_URL": "https://unreachable.example",
            "SPARK_CACHE_DIR": str(tmp_path / "l3"),
        },
    )
    await replacement.close()


async def test_runtime_closes_inspector_before_gateway_even_on_failure() -> None:
    from mcp_stdio.plugins.spark.plugin import SparkRuntime
    from mcp_stdio.plugins.spark.service import SparkEventLogService
    from mcp_stdio.plugins.spark.tools import SparkToolAdapter
    from tests.unit.plugins.spark.test_service import FakeGateway, FakeInspectionGateway

    order: list[str] = []

    class Download(FakeGateway):
        async def close(self) -> None:
            order.append("download")

    class Inspector(FakeInspectionGateway):
        async def close(self) -> None:
            order.append("inspection")
            raise RuntimeError("synthetic failure")

    gateway = Download()
    tools = SparkToolAdapter(
        service=SparkEventLogService(gateway=gateway, request_timeout_seconds=2), secret_values=()
    )
    runtime = SparkRuntime(tools, gateway, (), inspection_gateway=Inspector())
    with pytest.raises(RuntimeError):
        await runtime.close()
    assert order == ["inspection", "download"]
    await runtime.close()
    assert order == ["inspection", "download"]
