"""Hive inbound tool contract and safe-error tests."""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from typing import cast

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError as FastMCPToolError

from mcp_stdio.contracts.plugin import ToolHandler
from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation
from mcp_stdio.plugins.hive.gateway import HiveGatewayError
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
    schema = tools["get_table_schema"].inputSchema
    assert schema["type"] == "object"
    assert schema["required"] == ["database", "table"]
    assert schema["properties"] == {
        "database": {"title": "Database", "type": "string"},
        "table": {"title": "Table", "type": "string"},
        "include_ddl": {"default": False, "title": "Include Ddl", "type": "boolean"},
    }
    assert not {
        "sql",
        "where",
        "fragment",
        "statement",
        "query",
        "options",
    }.intersection(schema["properties"])

    assert tools["list_databases"].outputSchema == {
        "additionalProperties": False,
        "description": "Database names and their cache provenance.",
        "properties": {
            "databases": {
                "items": {"minLength": 1, "type": "string"},
                "title": "Databases",
                "type": "array",
            },
            "cached": {"title": "Cached", "type": "boolean"},
        },
        "required": ["databases", "cached"],
        "title": "ListDatabasesResult",
        "type": "object",
    }
