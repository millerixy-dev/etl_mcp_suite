"""Validated, secret-safe DolphinScheduler plugin configuration."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator

from mcp_stdio.core.config import SecretConfigModel, StrictConfigModel


class DolphinSchedulerSettings(StrictConfigModel):
    """Non-sensitive settings for the DolphinScheduler adapter."""

    base_url: str
    status_path: str = "/monitor/masters"
    request_timeout_seconds: Annotated[float, Field(gt=0, le=300)] = 30.0
    max_response_bytes: Annotated[int, Field(ge=1, le=8_388_608)] = 1_048_576
    max_detail_items: Annotated[int, Field(ge=1, le=1_000)] = 100
    default_page_size: Annotated[int, Field(ge=1, le=100)] = 10
    max_page_size: Annotated[int, Field(ge=1, le=200)] = 100
    max_log_bytes: Annotated[int, Field(ge=1, le=8_388_608)] = 1_048_576

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

    @field_validator("status_path")
    @classmethod
    def validate_status_path(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("status_path must start with '/'")
        if "?" in value or "#" in value:
            raise ValueError("status_path must not contain a query or fragment")
        return value


class DolphinSchedulerSecrets(SecretConfigModel):
    """Optional DolphinScheduler API token resolved from an environment variable."""

    token: SecretStr | None = None
