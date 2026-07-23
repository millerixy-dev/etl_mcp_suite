"""FastMCP stdio server adapter lifecycle tests."""

from __future__ import annotations

import asyncio

import pytest
from mcp.server.fastmcp import FastMCP

from mcp_stdio.contracts.plugin import BuiltinPluginName, ToolRegistrar
from mcp_stdio.core.server import StdioMcpServer


class CountingRuntime:
    """Minimal PluginRuntime that records registration and cleanup."""

    def __init__(self, name: BuiltinPluginName = "hive") -> None:
        self._name: BuiltinPluginName = name
        self.closed = False
        self.close_calls = 0
        self.registered: list[str | None] = []

    @property
    def name(self) -> BuiltinPluginName:
        return self._name

    @property
    def redaction_values(self) -> tuple[str, ...]:
        return ()

    def register_tools(self, registrar: ToolRegistrar) -> None:
        registrar.add_tool(self._tool, name="counting_tool")
        self.registered.append("counting_tool")

    async def close(self) -> None:
        self.close_calls += 1
        self.closed = True

    @staticmethod
    async def _tool() -> dict[str, bool]:
        return {"ok": True}


def test_construction_registers_only_the_runtime_tools() -> None:
    runtime = CountingRuntime("hive")
    server = StdioMcpServer(runtime)

    assert runtime.registered == ["counting_tool"]
    assert server.tool_names() == ["counting_tool"]


async def test_serve_closes_runtime_after_normal_stdio_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = CountingRuntime("hive")
    server = StdioMcpServer(runtime)

    async def fake_stdio(_self: object) -> None:
        return None

    monkeypatch.setattr(FastMCP, "run_stdio_async", fake_stdio)
    await server.serve()

    assert runtime.closed
    assert runtime.close_calls == 1


async def test_serve_closes_runtime_when_stdio_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = CountingRuntime("hive")
    server = StdioMcpServer(runtime)

    async def boom(_self: object) -> None:
        raise RuntimeError("startup failure")

    monkeypatch.setattr(FastMCP, "run_stdio_async", boom)

    with pytest.raises(RuntimeError, match="startup failure"):
        await server.serve()

    assert runtime.closed


async def test_serve_closes_runtime_on_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = CountingRuntime("hive")
    server = StdioMcpServer(runtime)

    async def cancelled(_self: object) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(FastMCP, "run_stdio_async", cancelled)

    with pytest.raises(asyncio.CancelledError):
        await server.serve()

    assert runtime.closed


def test_run_runs_stdio_and_closes_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = CountingRuntime("hive")
    server = StdioMcpServer(runtime)

    async def fake_stdio(_self: object) -> None:
        return None

    monkeypatch.setattr(FastMCP, "run_stdio_async", fake_stdio)
    server.run()

    assert runtime.closed
