"""Hive metadata and public result model tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mcp_stdio.plugins.hive.models import (
    ColumnMetadata,
    ListDatabasesResult,
    ListTablesResult,
    TableSchemaResult,
)


def test_column_metadata_preserves_complete_type_and_optional_comment() -> None:
    hive_type = "array<struct<x:int,y:map<string,array<decimal(10,2)>>>>"

    column = ColumnMetadata(name="payload", type=hive_type, comment=None, ordinal=1)
    empty_comment = ColumnMetadata(name="note", type="string", comment="", ordinal=2)

    assert column.type == hive_type
    assert column.comment is None
    assert empty_comment.comment == ""


@pytest.mark.parametrize("ordinal", [0, -1])
def test_column_metadata_requires_one_based_ordinal(ordinal: int) -> None:
    with pytest.raises(ValidationError):
        ColumnMetadata(name="payload", type="string", comment=None, ordinal=ordinal)


def test_hive_results_are_separate_typed_and_json_serializable() -> None:
    regular = ColumnMetadata(name="payload", type="string", comment="body", ordinal=1)
    partition = ColumnMetadata(name="dt", type="date", comment=None, ordinal=1)
    databases = ListDatabasesResult(databases=("default", "analytics"), cached=False)
    tables = ListTablesResult(database="analytics", tables=("events",), cached=True)
    schema = TableSchemaResult(
        database="analytics",
        table="events",
        columns=(regular,),
        partition_columns=(partition,),
        ddl="CREATE TABLE `analytics`.`events` (...) ",
        cached=False,
    )

    assert databases.model_dump(mode="json") == {
        "databases": ["default", "analytics"],
        "cached": False,
    }
    assert tables.model_dump(mode="json") == {
        "database": "analytics",
        "tables": ["events"],
        "cached": True,
    }
    assert schema.model_dump(mode="json") == {
        "database": "analytics",
        "table": "events",
        "columns": [
            {"name": "payload", "type": "string", "comment": "body", "ordinal": 1}
        ],
        "partition_columns": [
            {"name": "dt", "type": "date", "comment": None, "ordinal": 1}
        ],
        "ddl": "CREATE TABLE `analytics`.`events` (...) ",
        "cached": False,
    }


def test_schema_result_defaults_ddl_to_none() -> None:
    result = TableSchemaResult(
        database="default",
        table="events",
        columns=(),
        partition_columns=(),
        cached=False,
    )

    assert result.ddl is None


def test_domain_models_are_strict_frozen_and_reject_unknown_fields() -> None:
    result = ListDatabasesResult(databases=("default",), cached=False)

    with pytest.raises(ValidationError):
        result.cached = True
    with pytest.raises(ValidationError):
        ListDatabasesResult.model_validate(
            {"databases": ("default",), "cached": 1}, strict=True
        )
    with pytest.raises(ValidationError):
        ColumnMetadata.model_validate(
            {
                "name": "payload",
                "type": "string",
                "comment": None,
                "ordinal": 1,
                "extra": "not allowed",
            }
        )


@pytest.mark.parametrize("field", ["databases", "database", "table", "tables"])
def test_result_models_reject_unsafe_identifier_names(field: str) -> None:
    unsafe = "unsafe.name"
    constructors = {
        "databases": lambda: ListDatabasesResult(databases=(unsafe,), cached=False),
        "database": lambda: ListTablesResult(database=unsafe, tables=(), cached=False),
        "table": lambda: TableSchemaResult(
            database="default",
            table=unsafe,
            columns=(),
            partition_columns=(),
            cached=False,
        ),
        "tables": lambda: ListTablesResult(database="default", tables=(unsafe,), cached=False),
    }

    with pytest.raises(ValidationError):
        constructors[field]()
