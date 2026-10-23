"""Local, secret-safe Spark configuration."""

from __future__ import annotations

import base64
import ipaddress
import os
import re
import ssl
from pathlib import Path
from typing import Annotated
from urllib.parse import unquote, urlsplit

from pydantic import ConfigDict, Field, SecretStr, field_validator, model_validator

from mcp_stdio.core.config import ConfigError, SecretConfigModel, StrictConfigModel


class SparkSettings(StrictConfigModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    history_server_url: str
    cache_dir: str
    verify_tls: bool = True
    knox_sso_url: str | None = None
    ca_bundle_path: str | None = None
    request_timeout_seconds: Annotated[float, Field(gt=0, le=900)] = 300.0
    executor_log_node_manager_path: str | None = None
    executor_log_allowed_upstreams: list[str] = Field(default_factory=list)
    max_bytes: Annotated[int, Field(ge=1, le=1_073_741_824)] = 268_435_456

    @field_validator("executor_log_node_manager_path")
    @classmethod
    def validate_log_path(cls, value: str | None) -> str | None:
        if value is not None and (
            len(value) > 512 or not re.fullmatch(r"/(?:[A-Za-z0-9_-]+/)*node", value)
        ):
            raise ValueError("unsafe NodeManager gateway path")
        return value

    @field_validator("executor_log_allowed_upstreams")
    @classmethod
    def validate_log_rules(cls, values: list[str]) -> list[str]:
        if len(values) > 128 or len(set(values)) != len(values):
            raise ValueError("invalid upstream rules")
        for value in values:
            if len(value) > 512 or not re.fullmatch(
                r"https?://(?:\*\.)?[A-Za-z0-9.-]+:[0-9]{1,5}", value
            ):
                raise ValueError("invalid upstream rule")
            parts = urlsplit(value)
            host = parts.hostname or ""
            if not parts.port or not 1 <= parts.port <= 65535:
                raise ValueError("invalid upstream port")
            domain = host.removeprefix("*.")
            if any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in domain.split(".")
            ):
                raise ValueError("invalid upstream host")
            if host.startswith("*."):
                try:
                    ipaddress.ip_address(domain)
                except ValueError:
                    pass
                else:
                    raise ValueError("wildcard IP rules are forbidden")
            if value != value.lower():
                raise ValueError("upstream rules require canonical lowercase")
        return values

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

    @field_validator("knox_sso_url")
    @classmethod
    def validate_sso_url(cls, value: str | None) -> str | None:
        return cls.validate_url(value) if value is not None else None

    @model_validator(mode="after")
    def same_origin(self) -> SparkSettings:
        if (self.executor_log_node_manager_path is None) != (
            not self.executor_log_allowed_upstreams
        ):
            raise ValueError("log route and upstream rules must be configured together")
        if self.executor_log_node_manager_path is not None:
            if not urlsplit(self.history_server_url).path.endswith("/sparkhistory"):
                raise ValueError("log access requires a sparkhistory mount")
        if self.knox_sso_url is not None:
            source, login = urlsplit(self.history_server_url), urlsplit(self.knox_sso_url)
            if (source.hostname, source.port or 443) != (login.hostname, login.port or 443):
                raise ValueError("Knox SSO must share the History Server origin")
        return self


class SparkSecrets(SecretConfigModel):
    gateway_cookie: SecretStr | None = None
    username: SecretStr | None = None
    password: SecretStr | None = None

    @model_validator(mode="after")
    def validate_basic(self) -> SparkSecrets:
        if (self.username is None) != (self.password is None):
            raise ValueError("username and password must be supplied together")
        if self.username is not None:
            if self.gateway_cookie is not None:
                raise ValueError("Cookie and Basic credentials are mutually exclusive")
            for value in (self.username, self.password):
                if value is not None:
                    raw = value.get_secret_value()
                    if not raw.strip() or any(ord(c) < 32 or ord(c) == 127 for c in raw):
                        raise ValueError("invalid Basic credentials")
            if ":" in self.username.get_secret_value():
                raise ValueError("Basic username cannot contain a colon")
        return self

    @property
    def redaction_values(self) -> tuple[str, ...]:
        values = tuple(
            value.get_secret_value()
            for value in (self.gateway_cookie, self.username, self.password)
            if value is not None
        )
        # Only this field is a Cookie header; other secrets may contain '=' or ';'.
        if self.gateway_cookie is not None:
            for pair in self.gateway_cookie.get_secret_value().split(";"):
                _, separator, item = pair.partition("=")
                if separator and item.strip().strip('"'):
                    values += (item.strip().strip('"'),)
        if self.username is not None and self.password is not None:
            pair = f"{self.username.get_secret_value()}:{self.password.get_secret_value()}"
            values += (base64.b64encode(pair.encode("utf-8")).decode("ascii"),)
        return values

    @field_validator("gateway_cookie")
    @classmethod
    def validate_cookie(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            raw = value.get_secret_value()
            if not raw.strip() or any(c in raw for c in "\r\n\x00"):
                raise ValueError("invalid gateway Cookie")
        return value


def validate_auth(settings: SparkSettings, secrets: SparkSecrets) -> None:
    if (settings.knox_sso_url is None) != (secrets.username is None):
        raise ConfigError("Knox SSO URL and paired Basic credentials must be configured together")
