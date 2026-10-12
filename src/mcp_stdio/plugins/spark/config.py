"""Local, secret-safe Spark configuration."""

from __future__ import annotations

import os
import ssl
from pathlib import Path
from typing import Annotated
from urllib.parse import unquote, urlsplit

from pydantic import ConfigDict, Field, SecretStr, field_validator

from mcp_stdio.core.config import SecretConfigModel, StrictConfigModel


class SparkSettings(StrictConfigModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    history_server_url: str
    cache_dir: str
    ca_bundle_path: str | None = None
    request_timeout_seconds: Annotated[float, Field(gt=0, le=900)] = 300.0
    max_bytes: Annotated[int, Field(ge=1, le=1_073_741_824)] = 268_435_456

    @field_validator("history_server_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if len(value) > 2048 or any(ord(c) <= 32 or ord(c) == 127 for c in value):
            raise ValueError("invalid History Server URL")
        parts = urlsplit(value)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
        ):
            raise ValueError("History Server requires an absolute credential-free HTTPS URL")
        _ = parts.port
        decoded = parts.path
        for _ in range(3):
            decoded = unquote(decoded)
        if (
            "\\" in decoded
            or any(p in {".", ".."} for p in decoded.split("/"))
            or any(ord(c) < 32 or ord(c) == 127 for c in decoded)
        ):
            raise ValueError("unsafe History Server mount")
        return parts._replace(netloc=parts.netloc.lower(), path=parts.path.rstrip("/")).geturl()

    @field_validator("cache_dir", "ca_bundle_path")
    @classmethod
    def validate_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if (
            len(value) > 4096
            or not Path(value).is_absolute()
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
        ):
            raise ValueError("path must be a bounded absolute local path")
        return value

    @field_validator("cache_dir")
    @classmethod
    def validate_cache(cls, value: str) -> str:
        if os.name != "posix" or Path(value).is_symlink():
            raise ValueError("cache requires a POSIX directory without a symlink root")
        return value

    @field_validator("ca_bundle_path")
    @classmethod
    def validate_ca(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ssl.create_default_context(cafile=value)
            except (OSError, ssl.SSLError):
                raise ValueError("trusted CA bundle could not be loaded") from None
        return value


class SparkSecrets(SecretConfigModel):
    gateway_cookie: SecretStr | None = None

    @field_validator("gateway_cookie")
    @classmethod
    def validate_cookie(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            raw = value.get_secret_value()
            if not raw.strip() or any(c in raw for c in "\r\n\x00"):
                raise ValueError("invalid gateway Cookie")
        return value
