"""Validated, secret-safe Hive plugin configuration."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, SecretStr, field_validator

from mcp_stdio.core.config import SecretConfigModel, StrictConfigModel
from mcp_stdio.plugins.hive.identifiers import HiveIdentifierText


class HiveSettings(StrictConfigModel):
    """Non-sensitive settings for the fixed LDAP/binary Thrift adapter."""

    host: str
    port: Annotated[int, Field(ge=1, le=65_535)] = 10_000
    database: HiveIdentifierText = "default"
    cache_ttl_seconds: Annotated[int, Field(ge=0)] = 30

    @field_validator("host")
    @classmethod
    def require_non_empty_host(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("host must not be empty")
        return value


class HiveSecrets(SecretConfigModel):
    """LDAP credentials resolved from environment-variable references."""

    username: SecretStr
    password: SecretStr
