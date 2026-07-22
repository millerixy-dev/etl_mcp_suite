"""MCP- and PyHive-independent Hive metadata application service."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation
from mcp_stdio.plugins.hive.cache import HiveMetadataCache, make_hive_cache_key
from mcp_stdio.plugins.hive.gateway import (
    HiveGatewayError,
    HiveMetadataGateway,
)
from mcp_stdio.plugins.hive.identifiers import HiveIdentifier
from mcp_stdio.plugins.hive.models import (
    ListDatabasesResult,
    ListTablesResult,
    TableSchemaResult,
)
from mcp_stdio.plugins.hive.parser import (
    HiveResponseShapeError,
    parse_describe_rows,
    parse_show_create_rows,
)


def _service_error(
    *,
    category: ErrorCategory,
    operation: ToolOperation,
    identifiers: dict[str, str] | None = None,
) -> HiveGatewayError:
    return HiveGatewayError(
        ToolError.create(
            category=category,
            operation=operation,
            retryable=False,
            identifiers=identifiers,
        )
    )


def _validated_identifier(value: object, *, operation: ToolOperation) -> str:
    if not isinstance(value, str):
        raise _service_error(
            category=ErrorCategory.INVALID_INPUT,
            operation=operation,
        )
    try:
        return HiveIdentifier(value).value
    except ValueError:
        raise _service_error(
            category=ErrorCategory.INVALID_INPUT,
            operation=operation,
        ) from None


def _validated_include_ddl(value: object) -> bool:
    if type(value) is not bool:
        raise _service_error(
            category=ErrorCategory.INVALID_INPUT,
            operation=ToolOperation.GET_TABLE_SCHEMA,
        )
    return value


def _metadata_names(
    rows: object,
    *,
    operation: ToolOperation,
    identifiers: dict[str, str] | None = None,
) -> tuple[str, ...]:
    names: list[str] = []
    try:
        if not isinstance(rows, Sequence) or isinstance(
            rows, (str, bytes, bytearray)
        ):
            raise ValueError
        for raw_row in cast(Sequence[object], rows):
            if not isinstance(raw_row, Sequence) or isinstance(
                raw_row, (str, bytes, bytearray)
            ):
                raise ValueError
            row = cast(Sequence[object], raw_row)
            if len(row) != 1:
                raise ValueError
            name = row[0]
            if not isinstance(name, str) or not name.strip():
                raise ValueError
            names.append(name)
    except Exception:
        raise _service_error(
            category=ErrorCategory.UNEXPECTED_RESPONSE,
            operation=operation,
            identifiers=identifiers,
        ) from None
    return tuple(names)


class HiveSchemaService:
    """Coordinate validated metadata use cases and plugin-local caching."""

    def __init__(
        self,
        *,
        gateway: HiveMetadataGateway,
        cache: HiveMetadataCache,
    ) -> None:
        self._gateway = gateway
        self._cache = cache

    async def list_databases(self) -> ListDatabasesResult:
        async def load() -> ListDatabasesResult:
            rows = await self._gateway.list_databases()
            return ListDatabasesResult(
                databases=_metadata_names(
                    rows,
                    operation=ToolOperation.LIST_DATABASES,
                ),
                cached=False,
            )

        return await self._cache.get_or_load(
            make_hive_cache_key("list_databases"),
            load,
        )

    async def list_tables(self, database: object) -> ListTablesResult:
        database = _validated_identifier(
            database,
            operation=ToolOperation.LIST_TABLES,
        )
        identifiers = {"database": database}

        async def load() -> ListTablesResult:
            rows = await self._gateway.list_tables(database)
            return ListTablesResult(
                database=database,
                tables=_metadata_names(
                    rows,
                    operation=ToolOperation.LIST_TABLES,
                    identifiers=identifiers,
                ),
                cached=False,
            )

        return await self._cache.get_or_load(
            make_hive_cache_key("list_tables", database=database),
            load,
        )

    async def get_table_schema(
        self,
        database: object,
        table: object,
        include_ddl: object = False,
    ) -> TableSchemaResult:
        database = _validated_identifier(
            database,
            operation=ToolOperation.GET_TABLE_SCHEMA,
        )
        table = _validated_identifier(
            table,
            operation=ToolOperation.GET_TABLE_SCHEMA,
        )
        include_ddl = _validated_include_ddl(include_ddl)
        identifiers = {"database": database, "table": table}

        async def load() -> TableSchemaResult:
            try:
                describe_rows = await self._gateway.describe_table(database, table)
                columns, partition_columns = parse_describe_rows(describe_rows)
                ddl = None
                if include_ddl:
                    ddl_rows = await self._gateway.show_create_table(database, table)
                    ddl = parse_show_create_rows(ddl_rows)
            except HiveResponseShapeError:
                raise _service_error(
                    category=ErrorCategory.UNEXPECTED_RESPONSE,
                    operation=ToolOperation.GET_TABLE_SCHEMA,
                    identifiers=identifiers,
                ) from None
            return TableSchemaResult(
                database=database,
                table=table,
                columns=columns,
                partition_columns=partition_columns,
                ddl=ddl,
                cached=False,
            )

        return await self._cache.get_or_load(
            make_hive_cache_key(
                "get_table_schema",
                database=database,
                table=table,
                include_ddl=include_ddl,
            ),
            load,
        )
