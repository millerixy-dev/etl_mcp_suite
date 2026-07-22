"""Hive plugin composition-root tests."""

from __future__ import annotations

import json
import socket
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import cast

import pytest

from mcp_stdio.contracts.plugin import ToolHandler
from mcp_stdio.plugins.hive.config import HiveSecrets, HiveSettings
from mcp_stdio.plugins.hive.gateway import HiveRows
from mcp_stdio.plugins.hive.models import ListDatabasesResult, TableSchemaResult
from mcp_stdio.plugins.hive.plugin import PLUGIN_DEFINITION


class RecordingRegistrar:
    def __init__(self) -> None:
        self.tools: list[tuple[ToolHandler, str | None]] = []

    def add_tool(self, fn: ToolHandler, name: str | None = None) -> None:
        self.tools.append((fn, name))


class FakeAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    async def list_databases(self) -> HiveRows:
        self.calls.append(("list_databases",))
        return (("default",),)

    async def list_tables(self, database: str) -> HiveRows:
        self.calls.append(("list_tables", database))
        return (("events",),)

    async def describe_table(self, database: str, table: str) -> HiveRows:
        self.calls.append(("describe_table", database, table))
        return (("event_id", "bigint", None),)

    async def show_create_table(self, database: str, table: str) -> HiveRows:
        self.calls.append(("show_create_table", database, table))
        return (("CREATE TABLE",),)


def write_config(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "plugin": "hive",
                "settings": {
                    "host": "hive.example.internal",
                    "port": 10001,
                    "database": "catalog",
                    "cache_ttl_seconds": 45,
                },
                "secrets": {
                    "username": "HIVE_USERNAME",
                    "password": "HIVE_PASSWORD",
                },
            }
        ),
        encoding="utf-8",
    )
    return path


async def test_runtime_loads_config_without_network_and_registers_exact_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FakeAdapter()
    captured: list[tuple[HiveSettings, HiveSecrets]] = []

    def build_adapter(*, settings: HiveSettings, secrets: HiveSecrets) -> FakeAdapter:
        captured.append((settings, secrets))
        return adapter

    def reject_network(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("runtime construction attempted network access")

    monkeypatch.setattr(
        "mcp_stdio.plugins.hive.plugin.PyHiveMetadataAdapter",
        build_adapter,
    )
    monkeypatch.setattr(socket, "create_connection", reject_network)
    monkeypatch.setattr(socket.socket, "connect", reject_network)
    environment: Mapping[str, str] = {
        "HIVE_USERNAME": "runtime-user-sentinel",
        "HIVE_PASSWORD": "runtime-password-sentinel",
    }

    runtime = PLUGIN_DEFINITION.create_runtime(
        write_config(tmp_path / "hive.json"),
        environ=environment,
    )
    registrar = RecordingRegistrar()
    runtime.register_tools(registrar)

    assert runtime.name == "hive"
    assert [name for _, name in registrar.tools] == [
        "list_databases",
        "list_tables",
        "get_table_schema",
    ]
    assert len(captured) == 1
    settings, secrets = captured[0]
    assert settings == HiveSettings(
        host="hive.example.internal",
        port=10001,
        database="catalog",
        cache_ttl_seconds=45,
    )
    assert secrets.username.get_secret_value() == "runtime-user-sentinel"
    assert secrets.password.get_secret_value() == "runtime-password-sentinel"

    await runtime.close()
    await runtime.close()


async def test_runtime_wires_handlers_to_adapter_and_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FakeAdapter()

    def build_adapter(*, settings: HiveSettings, secrets: HiveSecrets) -> FakeAdapter:
        del settings, secrets
        return adapter

    monkeypatch.setattr(
        "mcp_stdio.plugins.hive.plugin.PyHiveMetadataAdapter",
        build_adapter,
    )
    runtime = PLUGIN_DEFINITION.create_runtime(
        write_config(tmp_path / "hive.json"),
        environ={
            "HIVE_USERNAME": "user-sentinel",
            "HIVE_PASSWORD": "password-sentinel",
        },
    )
    registrar = RecordingRegistrar()
    runtime.register_tools(registrar)
    handlers = {
        name: cast(Callable[..., Awaitable[object]], handler)
        for handler, name in registrar.tools
    }

    first = cast(ListDatabasesResult, await handlers["list_databases"]())
    second = cast(ListDatabasesResult, await handlers["list_databases"]())
    schema = cast(
        TableSchemaResult,
        await handlers["get_table_schema"]("default", "events", True),
    )

    assert first.cached is False
    assert second.cached is True
    assert schema.ddl == "CREATE TABLE"
    assert adapter.calls == [
        ("list_databases",),
        ("describe_table", "default", "events"),
        ("show_create_table", "default", "events"),
    ]
