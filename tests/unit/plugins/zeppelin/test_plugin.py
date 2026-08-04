"""Zeppelin plugin composition-root tests."""

from __future__ import annotations

import json
import socket
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import cast

import pytest
from mcp.server.fastmcp.exceptions import ToolError as FastMCPToolError

from mcp_stdio.contracts.plugin import ToolHandler
from mcp_stdio.plugins.zeppelin.plugin import PLUGIN_DEFINITION


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


async def test_runtime_loads_config_and_registers_exact_tools(
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

    assert runtime.name == "zeppelin"
    assert [name for _, name in registrar.tools] == [
        "list_notebooks",
        "create_notebook",
        "add_paragraph",
        "run_paragraph",
        "get_paragraph_status",
        "get_paragraph_result",
    ]

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
