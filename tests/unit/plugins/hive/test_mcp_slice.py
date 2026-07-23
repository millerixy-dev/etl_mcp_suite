"""End-to-end Hive vertical-slice MCP protocol loop.

These tests exercise the full inbound stack for one plugin slice -- MCP
client session over an in-memory transport, FastMCP tool dispatch, the real
HiveToolAdapter, the real HiveSchemaService, the real parser, and the real
cache -- with only the outbound gateway stubbed (FakeHiveGateway). No live
HiveServer2 and no network are required.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, cast

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

from mcp_stdio.plugins.hive.cache import HiveMetadataCache
from mcp_stdio.plugins.hive.gateway import HiveRows
from mcp_stdio.plugins.hive.service import HiveSchemaService
from mcp_stdio.plugins.hive.tools import HiveToolAdapter


@dataclass
class FakeHiveGateway:
    """Stub gateway returning canned metadata rows like PyHive would."""

    database_rows: HiveRows = (("default",), ("events_db",))
    table_rows: HiveRows = (("events",), ("clicks",))
    describe_rows: HiveRows = (
        ("event_id", "bigint", "identifier"),
        ("payload", "struct<a:int,b:array<string>>", ""),
        ("", "", ""),
        ("# Partition Information", "", ""),
        ("# col_name", "data_type", "comment"),
        ("event_date", "date", None),
    )
    ddl_rows: HiveRows = (
        ("CREATE TABLE `events_db`.`events` (",),
        ("  `event_id` bigint",),
        (")",),
    )
    failure: Exception | None = None
    calls: list[tuple[object, ...]] = field(
        default_factory=lambda: list[tuple[object, ...]]()
    )

    async def list_databases(self) -> HiveRows:
        self.calls.append(("list_databases",))
        self._raise_failure()
        return self.database_rows

    async def list_tables(self, database: str) -> HiveRows:
        self.calls.append(("list_tables", database))
        self._raise_failure()
        return self.table_rows

    async def describe_table(self, database: str, table: str) -> HiveRows:
        self.calls.append(("describe_table", database, table))
        self._raise_failure()
        return self.describe_rows

    async def show_create_table(self, database: str, table: str) -> HiveRows:
        self.calls.append(("show_create_table", database, table))
        self._raise_failure()
        return self.ddl_rows

    def _raise_failure(self) -> None:
        if self.failure is not None:
            raise self.failure


def _build_server(gateway: FakeHiveGateway) -> FastMCP[object]:
    service = HiveSchemaService(gateway=gateway, cache=HiveMetadataCache(0))
    adapter = HiveToolAdapter(service=service, secret_values=("real-secret-token",))
    fastmcp: FastMCP[object] = FastMCP(name="mcp-stdio")
    adapter.register_tools(fastmcp)
    return fastmcp


def _payload(result: object) -> dict[str, Any]:
    """Decode the JSON text content returned by a successful tool call."""

    content = result.content  # type: ignore[attr-defined]
    return cast(dict[str, Any], json.loads(content[0].text))  # type: ignore[union-attr]


def _error_payload(result: object) -> dict[str, Any]:
    """Decode the JSON embedded in a FastMCP tool-error text."""

    text = result.content[0].text  # type: ignore[attr-defined]
    return cast(dict[str, Any], json.loads(text.split(": ", 1)[1]))  # type: ignore[union-attr]


async def test_slice_lists_exact_three_tools_with_string_schemas() -> None:
    gateway = FakeHiveGateway()
    server = _build_server(gateway)

    async with create_connected_server_and_client_session(server) as session:
        await session.initialize()
        listed = await session.list_tools()

    tools = {tool.name: tool for tool in listed.tools}
    assert set(tools) == {"list_databases", "list_tables", "get_table_schema"}
    assert tools["list_databases"].inputSchema["properties"] == {}
    assert "database" in tools["list_tables"].inputSchema["properties"]
    schema = tools["get_table_schema"].inputSchema
    assert {"database", "table", "include_ddl"} <= set(schema["properties"])


async def test_slice_list_databases_round_trip() -> None:
    gateway = FakeHiveGateway()
    server = _build_server(gateway)

    async with create_connected_server_and_client_session(server) as session:
        await session.initialize()
        result = await session.call_tool("list_databases", {})

    assert result.isError is False
    payload = _payload(result)
    assert payload["databases"] == ["default", "events_db"]
    assert payload["cached"] is False
    assert gateway.calls == [("list_databases",)]


async def test_slice_list_tables_round_trip() -> None:
    gateway = FakeHiveGateway()
    server = _build_server(gateway)

    async with create_connected_server_and_client_session(server) as session:
        await session.initialize()
        result = await session.call_tool("list_tables", {"database": "events_db"})

    assert result.isError is False
    payload = _payload(result)
    assert payload["database"] == "events_db"
    assert payload["tables"] == ["events", "clicks"]
    assert payload["cached"] is False


async def test_slice_get_table_schema_with_ddl_round_trip() -> None:
    gateway = FakeHiveGateway()
    server = _build_server(gateway)

    async with create_connected_server_and_client_session(server) as session:
        await session.initialize()
        result = await session.call_tool(
            "get_table_schema",
            {"database": "events_db", "table": "events", "include_ddl": True},
        )

    assert result.isError is False
    payload = _payload(result)
    assert payload["database"] == "events_db"
    assert payload["table"] == "events"
    assert [col["name"] for col in payload["columns"]] == ["event_id", "payload"]
    assert payload["columns"][0]["type"] == "bigint"
    assert payload["columns"][0]["comment"] == "identifier"
    assert payload["columns"][1]["comment"] is None
    assert [col["name"] for col in payload["partition_columns"]] == ["event_date"]
    assert payload["ddl"] == "CREATE TABLE `events_db`.`events` (\n  `event_id` bigint\n)"
    assert payload["cached"] is False


async def test_slice_rejects_unsafe_database_name_with_invalid_input() -> None:
    gateway = FakeHiveGateway()
    server = _build_server(gateway)

    async with create_connected_server_and_client_session(server) as session:
        await session.initialize()
        result = await session.call_tool("list_tables", {"database": "ev; DROP--"})

    assert result.isError is True
    payload = _error_payload(result)
    assert payload["category"] == "INVALID_INPUT"
    assert gateway.calls == []


async def test_slice_maps_gateway_failure_to_safe_categorized_error() -> None:
    from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation
    from mcp_stdio.plugins.hive.gateway import HiveGatewayError

    gateway = FakeHiveGateway(
        failure=HiveGatewayError(
            ToolError.create(
                category=ErrorCategory.CONNECTION_FAILED,
                operation=ToolOperation.LIST_DATABASES,
                retryable=True,
            )
        )
    )
    server = _build_server(gateway)

    async with create_connected_server_and_client_session(server) as session:
        await session.initialize()
        result = await session.call_tool("list_databases", {})

    assert result.isError is True
    payload = _error_payload(result)
    assert payload["category"] == "CONNECTION_FAILED"
    assert payload["retryable"] is True
    assert "correlation_id" in payload
    assert "real-secret-token" not in json.dumps(payload)
