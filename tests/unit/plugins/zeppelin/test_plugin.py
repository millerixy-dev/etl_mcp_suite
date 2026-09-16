"""Zeppelin plugin composition-root tests."""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import cast

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError as FastMCPToolError

from mcp_stdio.contracts.plugin import ToolHandler
from mcp_stdio.plugins.zeppelin.http_client import ZeppelinHttpClient
from mcp_stdio.plugins.zeppelin.plugin import PLUGIN_DEFINITION
from tests.unit.plugins.zeppelin.test_http_client import (
    DiscoverySockets,
    DiscoveryTransport,
    discovery_adapter,
)
from tests.unit.plugins.zeppelin.test_websocket_client import LifecycleSocket


class RecordingRegistrar:
    def __init__(self) -> None:
        self.tools: list[tuple[ToolHandler, str | None]] = []

    def add_tool(self, fn: ToolHandler, name: str | None = None) -> None:
        self.tools.append((fn, name))


def write_config(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "plugin": "zeppelin",
                "settings": {
                    "base_url": "https://zeppelin.example/api",
                    "allowed_interpreters": ["spark.sql", "sh"],
                    "sql_write_allowed_databases": ["tmp_dc_ep"],
                    "sh_allowed_commands": ["echo"],
                },
                "secrets": {},
            }
        ),
        encoding="utf-8",
    )
    return path


def _reject_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("runtime attempted network access")

    monkeypatch.setattr(socket, "create_connection", reject)
    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket.socket, "connect_ex", reject)
    monkeypatch.setattr(socket, "getaddrinfo", reject)
    monkeypatch.setattr(socket, "gethostbyname", reject)


async def test_runtime_and_fastmcp_listing_are_network_free_with_exact_nine_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reject_network(monkeypatch)

    def reject_http(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("tool listing attempted an HTTP connection")

    async def reject_websocket(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("tool listing attempted a WebSocket connection")

    monkeypatch.setattr(
        "mcp_stdio.plugins.zeppelin.http_client.httpx.AsyncClient", reject_http,
    )
    monkeypatch.setattr(
        "mcp_stdio.plugins.zeppelin.websocket_client.SingleQueryConnection.__aenter__",
        reject_websocket,
    )
    runtime = PLUGIN_DEFINITION.create_runtime(
        write_config(tmp_path / "zeppelin.json"),
        environ={},
    )
    registrar = RecordingRegistrar()
    runtime.register_tools(registrar)
    server = FastMCP("zeppelin-plugin-contract")
    runtime.register_tools(server)
    listed = await server.list_tools()

    assert runtime.name == "zeppelin"
    assert [name for _, name in registrar.tools] == [
        "list_notebooks",
        "create_notebook",
        "add_paragraph",
        "run_paragraph",
        "get_paragraph_status",
        "get_paragraph_result",
        "get_interpreter_bindings",
        "restart_interpreter",
        "cancel_paragraph",
    ]
    assert [tool.name for tool in listed] == [name for _, name in registrar.tools]

    await runtime.close()
    await runtime.close()


async def test_runtime_wires_blacklist_hook_before_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reject_network(monkeypatch)
    runtime = PLUGIN_DEFINITION.create_runtime(
        write_config(tmp_path / "zeppelin.json"),
        environ={},
    )
    registrar = RecordingRegistrar()
    runtime.register_tools(registrar)
    handlers = {
        name: cast(Callable[..., Awaitable[object]], handler)
        for handler, name in registrar.tools
    }

    with pytest.raises(FastMCPToolError):
        await handlers["add_paragraph"](
            "nb-1", "title", "%spark.sql\nDROP TABLE tmp_dc_ep.my_table"
        )
    with pytest.raises(FastMCPToolError):
        await handlers["add_paragraph"](
            "nb-1", "title", "%spark.sql\nTRUNCATE TABLE tmp_dc_ep.my_table"
        )

    await runtime.close()


async def test_runtime_close_terminates_owned_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = DiscoveryTransport()
    socket = LifecycleSocket(pause="receive")
    gateway = discovery_adapter(transport, DiscoverySockets(socket))

    def client_factory(**_kwargs: object) -> ZeppelinHttpClient:
        return gateway

    monkeypatch.setattr(
        "mcp_stdio.plugins.zeppelin.plugin.ZeppelinHttpClient", client_factory,
    )
    runtime = PLUGIN_DEFINITION.create_runtime(write_config(tmp_path / "zeppelin.json"), environ={})
    task = asyncio.create_task(gateway.get_interpreter_bindings("first"))
    await socket.entered["receive"].wait()
    await runtime.close()
    await runtime.close()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(asyncio.CancelledError):
        await gateway.get_interpreter_bindings("second")
    assert socket.running == set()
    assert socket.closes == 1
    assert transport.closes == 1


async def test_concurrent_runtime_close_calls_both_wait_for_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = DiscoveryTransport()
    socket = LifecycleSocket(pause="close")
    gateway = discovery_adapter(transport, DiscoverySockets(socket))

    def client_factory(**_kwargs: object) -> ZeppelinHttpClient:
        return gateway

    monkeypatch.setattr(
        "mcp_stdio.plugins.zeppelin.plugin.ZeppelinHttpClient", client_factory,
    )
    runtime = PLUGIN_DEFINITION.create_runtime(write_config(tmp_path / "zeppelin.json"), environ={})
    task = asyncio.create_task(gateway.get_interpreter_bindings("first"))
    await socket.entered["close"].wait()
    first_close = asyncio.create_task(runtime.close())
    await asyncio.sleep(0)
    second_close = asyncio.create_task(runtime.close())
    await asyncio.sleep(0)
    try:
        assert not first_close.done()
        assert not second_close.done(), "a concurrent close returned with cleanup still active"
    finally:
        socket.release["close"].set()
        await asyncio.gather(task, first_close, second_close, return_exceptions=True)
    assert socket.running == set()
    assert socket.closes == transport.closes == 1
