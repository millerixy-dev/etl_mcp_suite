"""Hive inbound tool contract and safe-error tests."""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from typing import cast

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError as FastMCPToolError
from mcp.types import TextContent

from mcp_stdio.contracts.plugin import ToolHandler
from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation
from mcp_stdio.plugins.hive.cache import HiveMetadataCache
from mcp_stdio.plugins.hive.gateway import HiveGatewayError, HiveRows
from mcp_stdio.plugins.hive.models import (
    ColumnMetadata,
    ListDatabasesResult,
    ListTablesResult,
    TableSchemaResult,
)
from mcp_stdio.plugins.hive.service import HiveSchemaService
from mcp_stdio.plugins.hive.tools import HiveToolAdapter


class RecordingRegistrar:
    def __init__(self) -> None:
        self.tools: list[tuple[ToolHandler, str | None]] = []

    def add_tool(self, fn: ToolHandler, name: str | None = None) -> None:
        self.tools.append((fn, name))


class FakeHiveService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.failure: Exception | None = None

    async def list_databases(self) -> ListDatabasesResult:
        self.calls.append(("list_databases",))
        self._raise_failure()
        return ListDatabasesResult(databases=("default", "Sales Data"), cached=False)

    async def list_tables(self, database: str) -> ListTablesResult:
        self.calls.append(("list_tables", database))
        self._raise_failure()
        return ListTablesResult(database=database, tables=("events",), cached=True)

    async def get_table_schema(
        self,
        database: str,
        table: str,
        include_ddl: bool = False,
    ) -> TableSchemaResult:
        self.calls.append(("get_table_schema", database, table, include_ddl))
        self._raise_failure()
        return TableSchemaResult(
            database=database,
            table=table,
            columns=(
                ColumnMetadata(name="event_id", type="bigint", comment=None, ordinal=1),
            ),
            partition_columns=(),
            ddl="CREATE TABLE" if include_ddl else None,
            cached=False,
        )

    def _raise_failure(self) -> None:
        if self.failure is not None:
            raise self.failure


class RecordingGateway:
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


def tool_adapter(
    service: FakeHiveService,
    *,
    secret_values: tuple[str, ...] = (),
) -> HiveToolAdapter:
    return HiveToolAdapter(
        service=cast(HiveSchemaService, service),
        secret_values=secret_values,
    )


def registered_handlers(
    adapter: HiveToolAdapter,
) -> dict[str, Callable[..., Awaitable[object]]]:
    registrar = RecordingRegistrar()
    adapter.register_tools(registrar)
    return {
        cast(str, name): cast(Callable[..., Awaitable[object]], handler)
        for handler, name in registrar.tools
    }


def real_tool_server(
    gateway: RecordingGateway,
    *,
    secret_values: tuple[str, ...] = (),
) -> FastMCP:
    service = HiveSchemaService(
        gateway=gateway,
        cache=HiveMetadataCache(ttl_seconds=0),
    )
    server = FastMCP("hive-real-boundary")
    HiveToolAdapter(service=service, secret_values=secret_values).register_tools(server)
    return server


def safe_error_payload(error: FastMCPToolError) -> dict[str, object]:
    text = str(error)
    payload_start = text.find("{")
    assert payload_start >= 0
    payload = json.loads(text[payload_start:])
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


async def test_registers_exact_three_tools_with_narrow_public_signatures() -> None:
    adapter = tool_adapter(FakeHiveService())
    handlers = registered_handlers(adapter)

    assert tuple(handlers) == ("list_databases", "list_tables", "get_table_schema")
    assert tuple(inspect.signature(handlers["list_databases"]).parameters) == ()
    assert tuple(inspect.signature(handlers["list_tables"]).parameters) == ("database",)
    assert tuple(inspect.signature(handlers["get_table_schema"]).parameters) == (
        "database",
        "table",
        "include_ddl",
    )
    assert not {
        "sql",
        "where",
        "fragment",
        "statement",
        "query",
        "options",
    }.intersection(
        parameter
        for handler in handlers.values()
        for parameter in inspect.signature(handler).parameters
    )

    with pytest.raises(TypeError):
        await handlers["list_tables"]("default", sql="SELECT 1")


async def test_handlers_return_stable_typed_success_models() -> None:
    service = FakeHiveService()
    handlers = registered_handlers(tool_adapter(service))

    databases = await handlers["list_databases"]()
    tables = await handlers["list_tables"]("Analytics")
    schema = await handlers["get_table_schema"]("Analytics", "Events", True)

    assert isinstance(databases, ListDatabasesResult)
    assert databases.model_dump(mode="json") == {
        "databases": ["default", "Sales Data"],
        "cached": False,
    }
    assert isinstance(tables, ListTablesResult)
    assert tables.model_dump(mode="json") == {
        "database": "Analytics",
        "tables": ["events"],
        "cached": True,
    }
    assert isinstance(schema, TableSchemaResult)
    assert schema.model_dump(mode="json") == {
        "database": "Analytics",
        "table": "Events",
        "columns": [
            {"name": "event_id", "type": "bigint", "comment": None, "ordinal": 1}
        ],
        "partition_columns": [],
        "ddl": "CREATE TABLE",
        "cached": False,
    }
    assert service.calls == [
        ("list_databases",),
        ("list_tables", "Analytics"),
        ("get_table_schema", "Analytics", "Events", True),
    ]


async def test_gateway_error_raises_fastmcp_tool_error_with_safe_json() -> None:
    secret = "secret_identifier"
    service = FakeHiveService()
    domain_error = ToolError.create(
        category=ErrorCategory.NOT_FOUND,
        operation=ToolOperation.LIST_TABLES,
        retryable=False,
        identifiers={"database": secret},
    )
    service.failure = HiveGatewayError(domain_error)
    handler = registered_handlers(
        tool_adapter(service, secret_values=(secret,))
    )["list_tables"]

    with pytest.raises(FastMCPToolError) as captured:
        await handler(secret)

    payload = json.loads(str(captured.value))
    assert payload == domain_error.to_dict(secret_values=(secret,))
    assert payload["identifiers"] == {}
    assert secret not in str(captured.value)


async def test_unexpected_exception_maps_to_generic_safe_fastmcp_error() -> None:
    secret = "unexpected-secret-sentinel"
    service = FakeHiveService()
    service.failure = RuntimeError(f"raw backend failure {secret}")
    handler = registered_handlers(
        tool_adapter(service, secret_values=(secret,))
    )["list_databases"]

    with pytest.raises(FastMCPToolError) as captured:
        await handler()

    payload = json.loads(str(captured.value))
    assert payload["category"] == "UPSTREAM_ERROR"
    assert payload["operation"] == "list_databases"
    assert payload["message"] == "The upstream operation failed."
    assert payload["identifiers"] == {}
    assert secret not in str(captured.value)


async def test_fastmcp_schema_has_narrow_fields_and_strict_boolean_type() -> None:
    server = FastMCP("hive-contract")
    tool_adapter(FakeHiveService()).register_tools(server)

    tools = {tool.name: tool for tool in await server.list_tools()}

    assert tuple(tools) == ("list_databases", "list_tables", "get_table_schema")
    assert tools["list_databases"].inputSchema == {
        "properties": {},
        "title": "list_databasesArguments",
        "type": "object",
    }
    assert tools["list_tables"].inputSchema == {
        "properties": {
            "database": {"title": "Database", "type": "string"},
        },
        "required": ["database"],
        "title": "list_tablesArguments",
        "type": "object",
    }
    assert tools["get_table_schema"].inputSchema == {
        "properties": {
            "database": {"title": "Database", "type": "string"},
            "table": {"title": "Table", "type": "string"},
            "include_ddl": {
                "default": False,
                "title": "Include Ddl",
                "type": "boolean",
            },
        },
        "required": ["database", "table"],
        "title": "get_table_schemaArguments",
        "type": "object",
    }
    assert not {
        "sql",
        "where",
        "fragment",
        "statement",
        "query",
        "options",
    }.intersection(
        property_name
        for tool in tools.values()
        for property_name in tool.inputSchema["properties"]
    )

    assert tools["list_databases"].outputSchema == ListDatabasesResult.model_json_schema()
    assert tools["list_tables"].outputSchema == ListTablesResult.model_json_schema()
    assert tools["get_table_schema"].outputSchema == TableSchemaResult.model_json_schema()


async def test_fastmcp_call_tool_returns_structured_results_for_all_three_tools() -> None:
    server = FastMCP("hive-structured-contract")
    tool_adapter(FakeHiveService()).register_tools(server)

    expectations: list[tuple[str, dict[str, object], dict[str, object]]] = [
        (
            "list_databases",
            {},
            {"databases": ["default", "Sales Data"], "cached": False},
        ),
        (
            "list_tables",
            {"database": "Analytics"},
            {"database": "Analytics", "tables": ["events"], "cached": True},
        ),
        (
            "get_table_schema",
            {"database": "Analytics", "table": "Events", "include_ddl": True},
            {
                "database": "Analytics",
                "table": "Events",
                "columns": [
                    {
                        "name": "event_id",
                        "type": "bigint",
                        "comment": None,
                        "ordinal": 1,
                    }
                ],
                "partition_columns": [],
                "ddl": "CREATE TABLE",
                "cached": False,
            },
        ),
    ]

    for name, arguments, expected in expectations:
        raw_result = await server.call_tool(name, arguments)
        assert isinstance(raw_result, tuple)
        result = cast(tuple[list[TextContent], dict[str, object]], raw_result)
        content, structured = result
        assert structured == expected
        assert len(content) == 1
        assert json.loads(content[0].text) == expected


@pytest.mark.parametrize(
    "database",
    [1, 0, {"credential": "wire-input-secret-sentinel"}],
)
async def test_fastmcp_list_tables_routes_raw_invalid_input_to_safe_boundary(
    database: object,
) -> None:
    secret = "wire-input-secret-sentinel"
    gateway = RecordingGateway()
    server = real_tool_server(gateway, secret_values=(secret,))

    with pytest.raises(FastMCPToolError) as captured:
        await server.call_tool("list_tables", {"database": database})

    payload = safe_error_payload(captured.value)
    assert payload["category"] == "INVALID_INPUT"
    assert payload["operation"] == "list_tables"
    assert payload["identifiers"] == {}
    assert gateway.calls == []
    assert secret not in str(captured.value)


@pytest.mark.parametrize(
    ("arguments", "secret"),
    [
        ({"database": 1, "table": "events"}, "unused-sentinel"),
        ({"database": "default", "table": 0}, "unused-sentinel"),
        (
            {"database": "default", "table": {"secret": "table-wire-secret-sentinel"}},
            "table-wire-secret-sentinel",
        ),
        ({"database": "default", "table": "events", "include_ddl": 1}, "unused-sentinel"),
        ({"database": "default", "table": "events", "include_ddl": 0}, "unused-sentinel"),
        (
            {"database": "default", "table": "events", "include_ddl": "true"},
            "unused-sentinel",
        ),
        (
            {"database": "default", "table": "events", "include_ddl": "false"},
            "unused-sentinel",
        ),
        (
            {
                "database": "default",
                "table": "events",
                "include_ddl": {"token": "ddl-wire-secret-sentinel"},
            },
            "ddl-wire-secret-sentinel",
        ),
    ],
)
async def test_fastmcp_schema_routes_raw_non_strict_values_to_safe_boundary(
    arguments: dict[str, object],
    secret: str,
) -> None:
    gateway = RecordingGateway()
    server = real_tool_server(gateway, secret_values=(secret,))

    with pytest.raises(FastMCPToolError) as captured:
        await server.call_tool("get_table_schema", arguments)

    payload = safe_error_payload(captured.value)
    assert payload["category"] == "INVALID_INPUT"
    assert payload["operation"] == "get_table_schema"
    assert payload["identifiers"] == {}
    assert gateway.calls == []
    assert secret not in str(captured.value)
