"""Validated, secret-safe Zeppelin plugin configuration."""

from __future__ import annotations

import re
from typing import Annotated, cast
from urllib.parse import urlsplit

from pydantic import BeforeValidator, Field, SecretStr, field_validator, model_validator

from mcp_stdio.core.config import SecretConfigModel, StrictConfigModel


def _to_tuple(value: object) -> tuple[str, ...] | object:
    if isinstance(value, list):
        raw_items = cast(list[object], value)
        return tuple(str(item) for item in raw_items)
    return value


_INTERPRETER_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}")


class ZeppelinSettings(StrictConfigModel):
    """Non-sensitive settings for the Zeppelin REST adapter."""

    base_url: str
    request_timeout_seconds: Annotated[float, Field(gt=0, le=300)] = 30.0
    max_response_bytes: Annotated[int, Field(ge=1, le=8_388_608)] = 1_048_576
    max_result_bytes: Annotated[int, Field(ge=1, le=1_048_576)] = 65_536
    max_notebook_name_chars: Annotated[int, Field(ge=1, le=1_024)] = 256
    max_paragraph_title_chars: Annotated[int, Field(ge=1, le=1_024)] = 256
    max_paragraph_body_bytes: Annotated[int, Field(ge=1, le=1_048_576)] = 65_536
    max_opaque_id_chars: Annotated[int, Field(ge=1, le=4_096)] = 512
    allowed_interpreters: Annotated[tuple[str, ...], BeforeValidator(_to_tuple)] = ()

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https"):
            raise ValueError("base_url must use http or https")
        if parts.username or parts.password:
            raise ValueError("base_url must not contain credentials")
        if parts.query or parts.fragment:
            raise ValueError("base_url must not contain query or fragment")
        if not parts.netloc:
            raise ValueError("base_url must be absolute")
        path = parts.path.rstrip("/")
        return urlsplit(value)._replace(path=path).geturl()

    @field_validator("allowed_interpreters")
    @classmethod
    def validate_allowed_interpreters(
        cls, value: tuple[str, ...] | list[str]
    ) -> tuple[str, ...]:
        if isinstance(value, str):
            raise ValueError("allowed_interpreters must be a list")
        seen: set[str] = set()
        normalized: list[str] = []
        entries: tuple[str, ...] = tuple(value)
        for entry in entries:
            if not _INTERPRETER_PATTERN.fullmatch(entry):
                raise ValueError("interpreter name is malformed")
            if entry in seen:
                raise ValueError("interpreter names must be unique")
            seen.add(entry)
            normalized.append(entry)
        return tuple(normalized)


class ZeppelinSecrets(SecretConfigModel):
    """Optional paired Zeppelin session credentials from environment variables."""

    username: SecretStr | None = None
    password: SecretStr | None = None

    @model_validator(mode="after")
    def require_paired_credentials(self) -> ZeppelinSecrets:
        if (self.username is None) != (self.password is None):
            raise ValueError("username and password must both be present or both absent")
        return self
