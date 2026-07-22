"""MCP- and PyHive-independent Hive metadata gateway contract."""

from __future__ import annotations

from typing import Protocol, TypeAlias

from mcp_stdio.core.errors import ToolError

HiveRow: TypeAlias = tuple[object, ...]
HiveRows: TypeAlias = tuple[HiveRow, ...]


class HiveGatewayError(RuntimeError):
    """A categorized, safe failure crossing the Hive gateway boundary."""

    def __init__(self, tool_error: ToolError) -> None:
        self.tool_error = tool_error
        super().__init__(tool_error.message)


class HiveMetadataGateway(Protocol):
    """Fixed metadata operations required by the Hive application service."""

    async def list_databases(self) -> HiveRows:
        """Return materialized rows from ``SHOW DATABASES``."""

        ...

    async def list_tables(self, database: str) -> HiveRows:
        """Return materialized rows for one validated database."""

        ...

    async def describe_table(self, database: str, table: str) -> HiveRows:
        """Return materialized ``DESCRIBE`` rows for one validated table."""

        ...

    async def show_create_table(self, database: str, table: str) -> HiveRows:
        """Return materialized ``SHOW CREATE TABLE`` rows."""

        ...
