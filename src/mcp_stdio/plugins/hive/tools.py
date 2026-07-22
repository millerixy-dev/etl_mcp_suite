"""Inbound MCP tool adapters for the fixed Hive metadata surface."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Annotated, NoReturn

from mcp.server.fastmcp.exceptions import ToolError as FastMCPToolError
from pydantic import WithJsonSchema

from mcp_stdio.contracts.plugin import ToolRegistrar
from mcp_stdio.core.errors import ToolError, ToolOperation, unexpected_tool_error
from mcp_stdio.plugins.hive.gateway import HiveGatewayError
from mcp_stdio.plugins.hive.models import (
    ListDatabasesResult,
    ListTablesResult,
    TableSchemaResult,
)
from mcp_stdio.plugins.hive.service import HiveSchemaService

HiveToolString = Annotated[object, WithJsonSchema({"type": "string"})]
HiveToolBoolean = Annotated[object, WithJsonSchema({"type": "boolean"})]


class HiveToolAdapter:
    """Translate three typed inbound calls to the Hive application service."""

    def __init__(
        self,
        *,
        service: HiveSchemaService,
        secret_values: Iterable[str],
    ) -> None:
        self._service = service
        self._secret_values = tuple(value for value in secret_values if value)

    def register_tools(self, registrar: ToolRegistrar) -> None:
        """Register exactly the three approved Hive tools."""

        registrar.add_tool(self.list_databases, name="list_databases")
        registrar.add_tool(self.list_tables, name="list_tables")
        registrar.add_tool(self.get_table_schema, name="get_table_schema")

    async def list_databases(self) -> ListDatabasesResult:
        """List Hive databases without accepting caller-controlled SQL."""

        try:
            return await self._service.list_databases()
        except HiveGatewayError as error:
            self._raise_tool_error(error.tool_error)
        except Exception as error:
            self._raise_tool_error(
                unexpected_tool_error(
                    error,
                    operation=ToolOperation.LIST_DATABASES,
                )
            )

    async def list_tables(self, database: HiveToolString) -> ListTablesResult:
        """List tables in one validated Hive database."""

        try:
            return await self._service.list_tables(database)
        except HiveGatewayError as error:
            self._raise_tool_error(error.tool_error)
        except Exception as error:
            self._raise_tool_error(
                unexpected_tool_error(
                    error,
                    operation=ToolOperation.LIST_TABLES,
                )
            )

    async def get_table_schema(
        self,
        database: HiveToolString,
        table: HiveToolString,
        include_ddl: HiveToolBoolean = False,
    ) -> TableSchemaResult:
        """Return regular/partition columns and optionally fixed metadata DDL."""

        try:
            return await self._service.get_table_schema(
                database,
                table,
                include_ddl=include_ddl,
            )
        except HiveGatewayError as error:
            self._raise_tool_error(error.tool_error)
        except Exception as error:
            self._raise_tool_error(
                unexpected_tool_error(
                    error,
                    operation=ToolOperation.GET_TABLE_SCHEMA,
                )
            )

    def _raise_tool_error(self, error: ToolError) -> NoReturn:
        payload = error.to_dict(secret_values=self._secret_values)
        serialized = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        raise FastMCPToolError(serialized)
