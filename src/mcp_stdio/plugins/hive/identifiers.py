"""Validated Hive identifiers safe for fixed metadata statements."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated, cast

from pydantic import BeforeValidator

_HIVE_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


@dataclass(frozen=True, slots=True)
class HiveIdentifier:
    """An identifier that can be quoted only after exact validation."""

    value: str

    def __post_init__(self) -> None:
        value = cast(object, self.value)
        if not isinstance(value, str) or _HIVE_IDENTIFIER.fullmatch(value) is None:
            raise ValueError("Hive identifier must match [A-Za-z_][A-Za-z0-9_]*")

    @property
    def quoted(self) -> str:
        """Return the already-validated value in one pair of backticks."""

        return f"`{self.value}`"

    def __str__(self) -> str:
        return self.value


def _validate_identifier_text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Hive identifier must be a string")
    return HiveIdentifier(value).value


HiveIdentifierText = Annotated[str, BeforeValidator(_validate_identifier_text)]
"""Pydantic-compatible text form of an exact Hive identifier."""
