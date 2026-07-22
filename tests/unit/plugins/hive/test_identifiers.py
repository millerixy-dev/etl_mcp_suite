"""Hive identifier validation and quoting tests."""

from __future__ import annotations

import pytest

from mcp_stdio.plugins.hive.identifiers import HiveIdentifier


@pytest.mark.parametrize("value", ["a", "default", "_scratch", "Sales2026", "A_1"])
def test_valid_hive_identifier_is_quoted_only_after_validation(value: str) -> None:
    identifier = HiveIdentifier(value)

    assert str(identifier) == value
    assert identifier.quoted == f"`{value}`"


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "sales data",
        "sales-data",
        "sales.prod",
        "`sales`",
        "sales; DROP TABLE users",
        "1sales",
        "销售",
        "Ａdmin",
        "name\nnext",
    ],
)
def test_invalid_hive_identifier_is_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="Hive identifier"):
        HiveIdentifier(value)


def test_identifier_rejects_non_string_values_without_coercion() -> None:
    with pytest.raises(ValueError, match="Hive identifier"):
        HiveIdentifier(123)  # type: ignore[arg-type]
