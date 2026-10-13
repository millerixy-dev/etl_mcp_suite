"""Bounded HTTPS transport; no cache or Spark event interpretation."""

from __future__ import annotations

import asyncio
import os
import ssl
import time
from pathlib import Path

import httpx

from mcp_stdio.core.errors import ErrorCategory
from mcp_stdio.core.logging import suppress_http_transport_logging
from mcp_stdio.plugins.spark.config import SparkSecrets, SparkSettings, validate_auth
from mcp_stdio.plugins.spark.gateway import spark_error
from mcp_stdio.plugins.spark.models import FetchRequest


class SparkHttpClient:
    def __init__(
        self,
        *,
        settings: SparkSettings,
        secrets: SparkSecrets,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        validate_auth(settings, secrets)
        self._settings = settings
        self._secrets = secrets
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._closed = False

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._closed:
            raise spark_error(ErrorCategory.UPSTREAM_ERROR)
        if self._client is None:
            suppress_http_transport_logging()
            ca_path = self._settings.ca_bundle_path
            context: ssl.SSLContext | bool = self._settings.verify_tls
            if context and ca_path:
                context = ssl.create_default_context(cafile=ca_path)
            self._client = httpx.AsyncClient(
                verify=context,
                trust_env=False,
                follow_redirects=False,
                transport=self._transport,
                timeout=self._settings.request_timeout_seconds,
            )
        return self._client

    async def receive(
        self, application_id: str, attempt_id: str | None, destination: Path, *, deadline: float
    ) -> tuple[str, ...]:
        FetchRequest(application_id=application_id, attempt_id=attempt_id)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise spark_error(ErrorCategory.TIMEOUT, retryable=True)
        try:
            return await asyncio.wait_for(
                self._receive(application_id, attempt_id, destination, deadline),
                timeout=remaining,
            )
        except (asyncio.TimeoutError, httpx.TimeoutException):
            raise spark_error(
                ErrorCategory.TIMEOUT,
                application_id=application_id,
                attempt_id=attempt_id,
                retryable=True,
            ) from None
        except httpx.TransportError as exc:
            tls = isinstance(exc.__cause__, ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in str(exc)
            raise spark_error(
                ErrorCategory.CONNECTION_FAILED,
                application_id=application_id,
                attempt_id=attempt_id,
                retryable=not tls,
            ) from None
        except PermissionError:
            raise spark_error(ErrorCategory.PERMISSION_DENIED) from None
        except OSError:
            raise spark_error(ErrorCategory.UPSTREAM_ERROR) from None

    async def _receive(
        self, application_id: str, attempt_id: str | None, destination: Path, deadline: float
    ) -> tuple[str, ...]:
        client = self._ensure_client()
        suffix = f"/{attempt_id}/logs" if attempt_id is not None else "/logs"
        url = self._settings.history_server_url + f"/api/v1/applications/{application_id}" + suffix
        headers = {"Accept-Encoding": "identity"}
        if self._secrets.gateway_cookie is not None:
            headers["Cookie"] = self._secrets.gateway_cookie.get_secret_value()
        created = False
        complete = False
        try:
            await self._login(client, url, deadline)
            acquired = tuple(cookie.value for cookie in client.cookies.jar if cookie.value)
            async with client.stream(
                "GET", url, headers=headers, timeout=max(0.001, deadline - time.monotonic())
            ) as response:
                status = response.status_code
                category: ErrorCategory | None = None
                if status == 401 or 300 <= status < 400:
                    category = ErrorCategory.AUTHENTICATION_FAILED
                elif status == 403:
                    category = ErrorCategory.PERMISSION_DENIED
                elif status == 404:
                    category = ErrorCategory.NOT_FOUND
                elif status != 200:
                    category = ErrorCategory.UPSTREAM_ERROR
                if category is not None:
                    raise spark_error(
                        category,
                        application_id=application_id,
                        attempt_id=attempt_id,
                        retryable=status == 429 or status >= 500,
                    )
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise spark_error(ErrorCategory.UNEXPECTED_RESPONSE)
                fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                created = True
                total = 0
                prefix = bytearray()
                with os.fdopen(fd, "wb") as output:
                    async for chunk in response.aiter_raw(chunk_size=65536):
                        total += len(chunk)
                        if total > self._settings.max_bytes:
                            raise spark_error(
                                ErrorCategory.UPSTREAM_ERROR,
                                explanation="Event-log archive exceeds max_bytes.",
                            )
                        prefix.extend(chunk[: max(0, 512 - len(prefix))])
                        if time.monotonic() >= deadline:
                            raise spark_error(ErrorCategory.TIMEOUT, retryable=True)
                        output.write(chunk)
                        await asyncio.sleep(0)
                start = bytes(prefix).lstrip().lower()
                if start.startswith((b"<html", b"<!doctype html", b"<form")) or (
                    "text/html" in response.headers.get("content-type", "").lower()
                    and not prefix.startswith(b"PK\x03\x04")
                ):
                    raise spark_error(
                        ErrorCategory.AUTHENTICATION_FAILED,
                        application_id=application_id,
                        attempt_id=attempt_id,
                    )
                if not prefix.startswith(b"PK\x03\x04"):
                    raise spark_error(ErrorCategory.UNEXPECTED_RESPONSE)
                complete = True
                return acquired + tuple(
                    cookie.value for cookie in client.cookies.jar if cookie.value
                )
        finally:
            client.cookies.clear()
            if created and not complete:
                try:
                    os.unlink(destination)
                except FileNotFoundError:
                    pass

    async def _login(self, client: httpx.AsyncClient, download_url: str, deadline: float) -> None:
        username, password = self._secrets.username, self._secrets.password
        if username is None or password is None or self._settings.knox_sso_url is None:
            return
        client.cookies.clear()
        async with client.stream(
            "POST",
            self._settings.knox_sso_url,
            params={"originalUrl": self._settings.history_server_url + "/"},
            auth=httpx.BasicAuth(username.get_secret_value(), password.get_secret_value()),
            content=b"",
            timeout=max(0.001, deadline - time.monotonic()),
        ) as response:
            status = response.status_code
            if status not in {200, 204, 302, 303, 307, 308}:
                if status == 401 or 300 <= status < 400:
                    category = ErrorCategory.AUTHENTICATION_FAILED
                elif status == 403:
                    category = ErrorCategory.PERMISSION_DENIED
                else:
                    category = ErrorCategory.UPSTREAM_ERROR
                raise spark_error(category, retryable=status == 429 or status >= 500)
            if not client.build_request("GET", download_url).headers.get("Cookie"):
                raise spark_error(ErrorCategory.AUTHENTICATION_FAILED)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._client is not None:
            self._client.cookies.clear()
            await self._client.aclose()
