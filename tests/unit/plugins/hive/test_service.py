"""Hive application-service behavior and cache coordination tests."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation
from mcp_stdio.plugins.hive.cache import HiveMetadataCache
from mcp_stdio.plugins.hive.gateway import HiveGatewayError, HiveRows
from mcp_stdio.plugins.hive.service import HiveSchemaService


@dataclass
class FakeHiveGateway:
    database_rows: HiveRows = (("default",), ("Sales Data",), ("\u6570\u636e\u5e93",))
    table_rows: HiveRows = (("daily_events",), ("Display Table",))
    describe_rows: HiveRows = (
        ("event_id", "bigint", "identifier"),
        ("payload", "struct<a:int,b:array<string>>", ""),
        ("# Partition Information", "", ""),
        ("# col_name", "data_type", "comment"),
        ("event_date", "date", None),
    )
    ddl_rows: HiveRows = (("CREATE TABLE `daily_events` (",), ("  `event_id` bigint",), (")",))
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


def service_with(gateway: FakeHiveGateway, *, ttl: float = 30) -> HiveSchemaService:
    return HiveSchemaService(
        gateway=gateway,
        cache=HiveMetadataCache(ttl_seconds=ttl),
    )


async def test_list_databases_preserves_valid_upstream_names_and_caches_result() -> None:
    gateway = FakeHiveGateway()
    service = service_with(gateway)

    first = await service.list_databases()
    second = await service.list_databases()

    assert first.databases == ("default", "Sales Data", "\u6570\u636e\u5e93")
    assert first.cached is False
    assert second.databases == first.databases
    assert second.cached is True
    assert gateway.calls == [("list_databases",)]


async def test_list_tables_validates_before_gateway_and_preserves_upstream_names() -> None:
    gateway = FakeHiveGateway()
    service = service_with(gateway)

    result = await service.list_tables("Analytics")

    assert result.database == "Analytics"
    assert result.tables == ("daily_events", "Display Table")
    assert result.cached is False
    assert gateway.calls == [("list_tables", "Analytics")]


@pytest.mark.parametrize(
    "database",
    ["sales data", "bad.db", "`quoted`", "x; DROP TABLE y", 1, 0, {"bad": "value"}],
)
async def test_list_tables_rejects_unsafe_database_before_gateway(database: object) -> None:
    gateway = FakeHiveGateway()
    service = service_with(gateway)

    with pytest.raises(HiveGatewayError) as captured:
        await service.list_tables(database)  # type: ignore[arg-type]

    assert captured.value.tool_error.category is ErrorCategory.INVALID_INPUT
    assert captured.value.tool_error.operation is ToolOperation.LIST_TABLES
    assert captured.value.tool_error.identifiers == {}
    assert gateway.calls == []


async def test_get_table_schema_parses_columns_without_requesting_ddl() -> None:
    gateway = FakeHiveGateway()
    service = service_with(gateway)

    result = await service.get_table_schema("Analytics", "Daily_Events")

    assert result.database == "Analytics"
    assert result.table == "Daily_Events"
    assert [(item.name, item.type, item.comment, item.ordinal) for item in result.columns] == [
        ("event_id", "bigint", "identifier", 1),
        ("payload", "struct<a:int,b:array<string>>", None, 2),
    ]
    assert [(item.name, item.ordinal) for item in result.partition_columns] == [
        ("event_date", 1)
    ]
    assert result.ddl is None
    assert result.cached is False
    assert gateway.calls == [("describe_table", "Analytics", "Daily_Events")]


async def test_get_table_schema_requests_and_parses_ddl_only_when_enabled() -> None:
    gateway = FakeHiveGateway()
    service = service_with(gateway)

    first = await service.get_table_schema(
        "Analytics", "Daily_Events", include_ddl=True
    )
    second = await service.get_table_schema(
        "analytics", "daily_events", include_ddl=True
    )

    assert first.ddl == "CREATE TABLE `daily_events` (\n  `event_id` bigint\n)"
    assert first.cached is False
    assert second.ddl == first.ddl
    assert second.cached is True
    assert gateway.calls == [
        ("describe_table", "Analytics", "Daily_Events"),
        ("show_create_table", "Analytics", "Daily_Events"),
    ]


@pytest.mark.parametrize(
    ("database", "table"),
    [
        ("bad database", "events"),
        ("default", "events; SELECT 1"),
        ("default", "db.table"),
        (1, "events"),
        ("default", 0),
        ({"bad": "value"}, "events"),
    ],
)
async def test_get_table_schema_rejects_unsafe_identifiers_before_gateway(
    database: object, table: object
) -> None:
    gateway = FakeHiveGateway()
    service = service_with(gateway)

    with pytest.raises(HiveGatewayError) as captured:
        await service.get_table_schema(database, table)  # type: ignore[arg-type]

    assert captured.value.tool_error.category is ErrorCategory.INVALID_INPUT
    assert captured.value.tool_error.operation is ToolOperation.GET_TABLE_SCHEMA
    assert captured.value.tool_error.identifiers == {}
    assert gateway.calls == []


async def test_get_table_schema_rejects_non_boolean_ddl_flag_before_gateway() -> None:
    gateway = FakeHiveGateway()
    service = service_with(gateway)

    with pytest.raises(HiveGatewayError) as captured:
        await service.get_table_schema(
            "default",
            "events",
            include_ddl=1,  # type: ignore[arg-type]
        )

    assert captured.value.tool_error.category is ErrorCategory.INVALID_INPUT
    assert captured.value.tool_error.operation is ToolOperation.GET_TABLE_SCHEMA
    assert gateway.calls == []


@pytest.mark.parametrize(
    ("method", "rows", "expected_operation", "identifiers"),
    [
        ("list_databases", (("default", "extra"),), ToolOperation.LIST_DATABASES, {}),
        ("list_databases", (("",),), ToolOperation.LIST_DATABASES, {}),
        (
            "list_tables",
            ((object(),),),
            ToolOperation.LIST_TABLES,
            {"database": "default"},
        ),
        (
            "get_table_schema",
            (("only", "two"),),
            ToolOperation.GET_TABLE_SCHEMA,
            {"database": "default", "table": "events"},
        ),
    ],
)
async def test_unsupported_response_shapes_map_to_safe_unexpected_response(
    method: str,
    rows: HiveRows,
    expected_operation: ToolOperation,
    identifiers: dict[str, str],
) -> None:
    gateway = FakeHiveGateway()
    if method == "list_databases":
        gateway.database_rows = rows
    elif method == "list_tables":
        gateway.table_rows = rows
    else:
        gateway.describe_rows = rows
    service = service_with(gateway)

    with pytest.raises(HiveGatewayError) as captured:
        if method == "list_databases":
            await service.list_databases()
        elif method == "list_tables":
            await service.list_tables("default")
        else:
            await service.get_table_schema("default", "events")

    error = captured.value.tool_error
    assert error.category is ErrorCategory.UNEXPECTED_RESPONSE
    assert error.operation is expected_operation
    assert error.identifiers == identifiers
    assert "object" not in repr(error.to_dict(secret_values=()))


async def test_ddl_parse_failure_does_not_cache_partial_schema() -> None:
    gateway = FakeHiveGateway(ddl_rows=((object(),),))
    service = service_with(gateway)

    for _ in range(2):
        with pytest.raises(HiveGatewayError) as captured:
            await service.get_table_schema("default", "events", include_ddl=True)
        assert captured.value.tool_error.category is ErrorCategory.UNEXPECTED_RESPONSE

    assert gateway.calls == [
        ("describe_table", "default", "events"),
        ("show_create_table", "default", "events"),
    ] * 2


async def test_gateway_error_is_propagated_without_cache_storage() -> None:
    upstream = HiveGatewayError(
        ToolError.create(
            category=ErrorCategory.CONNECTION_FAILED,
            operation=ToolOperation.LIST_DATABASES,
            retryable=True,
        )
    )
    gateway = FakeHiveGateway(failure=upstream)
    service = service_with(gateway)

    for _ in range(2):
        with pytest.raises(HiveGatewayError) as captured:
            await service.list_databases()
        assert captured.value.tool_error is upstream.tool_error

    assert gateway.calls == [("list_databases",), ("list_databases",)]
