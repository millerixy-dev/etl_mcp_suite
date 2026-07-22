"""HiveServer2 metadata response parser tests."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from mcp_stdio.plugins.hive.models import ColumnMetadata
from mcp_stdio.plugins.hive.parser import (
    HiveResponseShapeError,
    parse_describe_rows,
    parse_show_create_rows,
)


def test_parse_describe_returns_normal_columns_with_one_based_ordinals() -> None:
    columns, partition_columns = parse_describe_rows(
        [
            ("event_id", "bigint", "identifier"),
            ("payload", "string", None),
        ]
    )

    assert columns == (
        ColumnMetadata(name="event_id", type="bigint", comment="identifier", ordinal=1),
        ColumnMetadata(name="payload", type="string", comment=None, ordinal=2),
    )
    assert partition_columns == ()


def test_parse_describe_separates_partition_columns_and_restarts_ordinals() -> None:
    columns, partition_columns = parse_describe_rows(
        [
            ("event_id", "bigint", ""),
            ("# Partition Information", "", ""),
            ("", "", ""),
            ("# col_name", "data_type", "comment"),
            ("dt", "date", "partition date"),
            ("region", "string", None),
        ]
    )

    assert [column.ordinal for column in columns] == [1]
    assert [column.name for column in partition_columns] == ["dt", "region"]
    assert [column.ordinal for column in partition_columns] == [1, 2]


def test_parse_describe_ignores_repeated_headers_and_blank_rows_around_transition() -> None:
    columns, partition_columns = parse_describe_rows(
        [
            ("# col_name", "data_type", "comment"),
            ("payload", "string", ""),
            (None, None, None),
            ("# Partition Information", None, None),
            ("   ", "\t", None),
            ("# col_name", "data_type", "comment"),
            ("# col_name", "data_type", "comment"),
            ("dt", "string", ""),
        ]
    )

    assert [column.name for column in columns] == ["payload"]
    assert [column.name for column in partition_columns] == ["dt"]


def test_parse_describe_preserves_nested_complex_types_and_normalizes_comments() -> None:
    nested_type = "array<struct<x:int,y:map<string,array<decimal(10,2)>>>>"

    columns, _ = parse_describe_rows(
        [
            (" payload.value/原文 ", f" {nested_type} ", "   "),
            ("note", "string", "  populated comment  "),
        ]
    )

    assert columns == (
        ColumnMetadata(name="payload.value/原文", type=nested_type, comment=None, ordinal=1),
        ColumnMetadata(
            name="note", type="string", comment="populated comment", ordinal=2
        ),
    )


def test_parse_show_create_joins_first_column_rows_in_order() -> None:
    ddl = parse_show_create_rows(
        [
            ("CREATE TABLE `events` (",),
            ("  `event_id` bigint",),
            (")",),
        ]
    )

    assert ddl == "CREATE TABLE `events` (\n  `event_id` bigint\n)"


def test_parse_show_create_preserves_a_single_multiline_row() -> None:
    ddl = "CREATE TABLE `events` (\n  `event_id` bigint\n)\nSTORED AS ORC"

    assert parse_show_create_rows([(ddl,)]) == ddl


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [("only-name", "string")],
        [("name", 7, None)],
        [(7, "string", None)],
        [("name", "string", object())],
        [("", "string", None)],
        [("name", "", None)],
        [("# Partition Information", "unexpected", "")],
        [("name", "string", None), ("# Partition Info", "", "")],
        [("# Partition Information", "", ""), ("dt", "string", None)],
        [("name", "string", None), ("# Partition Information", "", "")],
        ["not-a-row"],
    ],
)
def test_parse_describe_rejects_malformed_rows_with_safe_errors(
    rows: list[object],
) -> None:
    secret = "credential-value-must-not-leak"
    materialized_rows = [*rows, (secret,)] if rows == [("only-name", "string")] else rows

    with pytest.raises(HiveResponseShapeError) as captured:
        parse_describe_rows(materialized_rows)

    assert secret not in str(captured.value)
    assert len(str(captured.value)) <= 96


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [()],
        [("",)],
        [("   ",)],
        [(None,)],
        [(7,)],
        [("CREATE TABLE secret", "unexpected")],
        ["not-a-row"],
    ],
)
def test_parse_show_create_rejects_empty_or_invalid_rows_with_safe_errors(
    rows: list[object],
) -> None:
    with pytest.raises(HiveResponseShapeError) as captured:
        parse_show_create_rows(rows)

    assert "CREATE TABLE secret" not in str(captured.value)
    assert len(str(captured.value)) <= 96


@pytest.mark.parametrize("parser", [parse_describe_rows, parse_show_create_rows])
def test_parser_shape_error_does_not_echo_malformed_row(
    parser: Callable[[list[object]], object],
) -> None:
    secret = "ldap-password-like-secret"

    with pytest.raises(HiveResponseShapeError) as captured:
        parser([(secret, object())])

    assert secret not in str(captured.value)
