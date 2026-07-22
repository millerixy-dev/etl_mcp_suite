"""Strict Hive metadata and tool result models."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from mcp_stdio.plugins.hive.identifiers import HiveIdentifierText


class HiveDomainModel(BaseModel):
    """Immutable, strict base for metadata values crossing plugin layers."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ColumnMetadata(HiveDomainModel):
    """One regular or partition column returned by Hive metadata."""

    name: HiveIdentifierText
    type: Annotated[str, Field(min_length=1)]
    comment: str | None = None
    ordinal: Annotated[int, Field(ge=1)]


class ListDatabasesResult(HiveDomainModel):
    """Database names and their cache provenance."""

    databases: tuple[HiveIdentifierText, ...]
    cached: bool


class ListTablesResult(HiveDomainModel):
    """Table names for one validated database."""

    database: HiveIdentifierText
    tables: tuple[HiveIdentifierText, ...]
    cached: bool


class TableSchemaResult(HiveDomainModel):
    """Separated regular/partition metadata plus optional DDL."""

    database: HiveIdentifierText
    table: HiveIdentifierText
    columns: tuple[ColumnMetadata, ...]
    partition_columns: tuple[ColumnMetadata, ...]
    ddl: str | None = None
    cached: bool
