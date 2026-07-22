"""Pure parsers for materialized HiveServer2 metadata rows."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Literal, cast

from mcp_stdio.plugins.hive.models import ColumnMetadata

_ResponseKind = Literal["DESCRIBE", "SHOW CREATE TABLE"]
_PARTITION_MARKER = "# Partition Information"
_COLUMN_HEADER = "# col_name"


class HiveResponseShapeError(ValueError):
    """A bounded internal error for unsupported Hive metadata row shapes."""

    def __init__(self, response_kind: _ResponseKind) -> None:
        super().__init__(f"{response_kind} response has an unsupported shape.")


def _row_of_length(
    raw_row: object,
    *,
    length: int,
    response_kind: _ResponseKind,
) -> Sequence[object]:
    if not isinstance(raw_row, Sequence) or isinstance(raw_row, (str, bytes, bytearray)):
        raise HiveResponseShapeError(response_kind)
    row = cast(Sequence[object], raw_row)
    if len(row) != length:
        raise HiveResponseShapeError(response_kind)
    return row


def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _is_column_header(row: Sequence[object]) -> bool:
    data_type = row[1]
    comment = row[2]
    return (
        isinstance(data_type, str)
        and data_type.strip() == "data_type"
        and (
            _is_blank(comment)
            or (isinstance(comment, str) and comment.strip() == "comment")
        )
    )


def parse_describe_rows(
    rows: Iterable[object],
) -> tuple[tuple[ColumnMetadata, ...], tuple[ColumnMetadata, ...]]:
    """Parse strict three-cell DESCRIBE rows into regular and partition columns."""

    columns: list[ColumnMetadata] = []
    partition_columns: list[ColumnMetadata] = []
    parsing_partitions = False

    for raw_row in rows:
        row = _row_of_length(raw_row, length=3, response_kind="DESCRIBE")
        if all(_is_blank(value) for value in row):
            continue

        raw_name = row[0]
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise HiveResponseShapeError("DESCRIBE")
        name = raw_name.strip()

        if name == _PARTITION_MARKER:
            if (
                parsing_partitions
                or not columns
                or not all(_is_blank(value) for value in row[1:])
            ):
                raise HiveResponseShapeError("DESCRIBE")
            parsing_partitions = True
            continue

        if name == _COLUMN_HEADER:
            if not _is_column_header(row):
                raise HiveResponseShapeError("DESCRIBE")
            continue

        if name.startswith("#"):
            raise HiveResponseShapeError("DESCRIBE")

        raw_type = row[1]
        raw_comment = row[2]
        if not isinstance(raw_type, str) or not raw_type.strip():
            raise HiveResponseShapeError("DESCRIBE")
        if raw_comment is not None and not isinstance(raw_comment, str):
            raise HiveResponseShapeError("DESCRIBE")

        target = partition_columns if parsing_partitions else columns
        comment = None if raw_comment is None or not raw_comment.strip() else raw_comment.strip()
        target.append(
            ColumnMetadata(
                name=name,
                type=raw_type.strip(),
                comment=comment,
                ordinal=len(target) + 1,
            )
        )

    if not columns or (parsing_partitions and not partition_columns):
        raise HiveResponseShapeError("DESCRIBE")
    return tuple(columns), tuple(partition_columns)


def parse_show_create_rows(rows: Iterable[object]) -> str:
    """Join ordered single-cell SHOW CREATE TABLE rows without normalizing SQL."""

    ddl_parts: list[str] = []
    for raw_row in rows:
        row = _row_of_length(raw_row, length=1, response_kind="SHOW CREATE TABLE")
        ddl_part = row[0]
        if not isinstance(ddl_part, str) or not ddl_part.strip():
            raise HiveResponseShapeError("SHOW CREATE TABLE")
        ddl_parts.append(ddl_part)

    if not ddl_parts:
        raise HiveResponseShapeError("SHOW CREATE TABLE")
    return "\n".join(ddl_parts)
