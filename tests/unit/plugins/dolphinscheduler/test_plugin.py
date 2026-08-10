"""DolphinScheduler plugin composition-root tests."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from mcp_stdio.contracts.plugin import ToolHandler
from mcp_stdio.plugins.dolphinscheduler.plugin import PLUGIN_DEFINITION


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
                "plugin": "dolphinscheduler",
                "settings": {"base_url": "http://ds.example:12345/dolphinscheduler"},
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


async def test_runtime_loads_config_and_registers_exact_tool_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reject_network(monkeypatch)
    runtime = PLUGIN_DEFINITION.create_runtime(
        write_config(tmp_path / "dolphinscheduler.json"),
        environ={},
    )
    registrar = RecordingRegistrar()
    runtime.register_tools(registrar)

    assert runtime.name == "dolphinscheduler"
    assert [name for _, name in registrar.tools] == [
        "get_server_status",
        "list_objects",
        "get_object",
        "search_objects",
        "start_workflow",
        "get_task_log",
        "extract_log_links",
    ]

    await runtime.close()


async def test_runtime_closes_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reject_network(monkeypatch)
    runtime = PLUGIN_DEFINITION.create_runtime(
        write_config(tmp_path / "dolphinscheduler.json"),
        environ={},
    )
    await runtime.close()
    await runtime.close()
