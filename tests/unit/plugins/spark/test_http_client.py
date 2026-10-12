"""Bounded History Server GET tests using synthetic responses."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import ssl
import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from mcp_stdio.plugins.spark.config import SparkSecrets, SparkSettings
from mcp_stdio.plugins.spark.gateway import SparkGatewayError


class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes], delay: float = 0) -> None:
        self.chunks = chunks
        self.delay = delay
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            await asyncio.sleep(self.delay)
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


def _client(
    tmp_path: Path,
    transport: httpx.AsyncBaseTransport,
    max_bytes: int = 10000,
    *,
    verify_tls: bool = True,
):
    from mcp_stdio.plugins.spark.http_client import SparkHttpClient

    return SparkHttpClient(
        settings=SparkSettings(
            history_server_url="https://history.example/gateway/sparkhistory",
            cache_dir=str(tmp_path),
            max_bytes=max_bytes,
            verify_tls=verify_tls,
        ),
        secrets=SparkSecrets(gateway_cookie=SecretStr("session=synthetic-cookie")),
        transport=transport,
    )


@pytest.mark.parametrize("attempt", [None, "1"])
@pytest.mark.parametrize("verify_tls", [True, False])
async def test_path_cookie_lazy_and_safe_tls(
    tmp_path: Path, attempt: str | None, verify_tls: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[httpx.Request] = []
    options: list[dict[str, object]] = []
    original = httpx.AsyncClient

    def factory(**kwargs: object) -> httpx.AsyncClient:
        options.append(kwargs)
        return original(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", factory)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, stream=Stream([b"PK\x03\x04synthetic-zip"]))

    client = _client(tmp_path, httpx.MockTransport(handler), verify_tls=verify_tls)
    assert not options
    try:
        await client.receive(
            "application_1_42", attempt, tmp_path / "archive.part", deadline=time.monotonic() + 2
        )
        suffix = "/1/logs" if attempt else "/logs"
        assert (
            requests[0].url.path
            == "/gateway/sparkhistory/api/v1/applications/application_1_42" + suffix
        )
        assert requests[0].headers["Cookie"] == "session=synthetic-cookie"
        assert options[0]["trust_env"] is False
        assert options[0]["follow_redirects"] is False
        assert options[0]["verify"] is verify_tls
        assert (tmp_path / "archive.part").stat().st_mode & 0o777 == 0o600
    finally:
        await client.close()
        await client.close()


@pytest.mark.parametrize(
    ("status", "body", "category"),
    [
        (200, b"<html>synthetic-cookie login</html>", "AUTHENTICATION_FAILED"),
        (302, b"", "AUTHENTICATION_FAILED"),
        (401, b"secret", "AUTHENTICATION_FAILED"),
        (403, b"secret", "PERMISSION_DENIED"),
        (404, b"secret", "NOT_FOUND"),
        (429, b"secret", "UPSTREAM_ERROR"),
        (500, b"secret", "UPSTREAM_ERROR"),
        (200, b"unexpected", "UNEXPECTED_RESPONSE"),
    ],
)
async def test_safe_status_and_html(
    tmp_path: Path, status: int, body: bytes, category: str
) -> None:
    stream = Stream([body])
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, stream=stream, headers={"location": "https://other.example"})

    client = _client(tmp_path, httpx.MockTransport(handler))
    try:
        with pytest.raises(SparkGatewayError) as error:
            await client.receive(
                "application_1_42", "1", tmp_path / "archive.part", deadline=time.monotonic() + 2
            )
        assert error.value.tool_error.category.value == category
        assert "synthetic-cookie" not in str(error.value)
        assert calls == 1
        assert stream.closed
        assert not (tmp_path / "archive.part").exists()
    finally:
        await client.close()


async def test_actual_byte_limit_and_cleanup(tmp_path: Path) -> None:
    stream = Stream([b"PK\x03\x04", b"x" * 100])
    client = _client(
        tmp_path,
        httpx.MockTransport(lambda request: httpx.Response(200, stream=stream)),
        max_bytes=50,
    )
    try:
        with pytest.raises(SparkGatewayError) as error:
            await client.receive(
                "application_1_42", None, tmp_path / "archive.part", deadline=time.monotonic() + 2
            )
        assert error.value.tool_error.category.value == "UPSTREAM_ERROR"
        assert stream.closed
        assert not (tmp_path / "archive.part").exists()
    finally:
        await client.close()


@pytest.mark.parametrize("cancel", [False, True])
async def test_deadline_and_cancel_close_stream(tmp_path: Path, cancel: bool) -> None:
    stream = Stream([b"PK\x03\x04", b"other"], delay=1)
    client = _client(
        tmp_path, httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
    )
    task = asyncio.create_task(
        client.receive(
            "application_1_42",
            None,
            tmp_path / "archive.part",
            deadline=time.monotonic() + (2 if cancel else 0.03),
        )
    )
    try:
        if cancel:
            await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(SparkGatewayError) as error:
                await task
            assert error.value.tool_error.category.value == "TIMEOUT"
        assert stream.closed
        assert not (tmp_path / "archive.part").exists()
    finally:
        await client.close()


async def test_default_tls_ignores_ambient_ca_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mcp_stdio.plugins.spark.http_client import SparkHttpClient

    calls: list[str | None] = []
    contexts: list[ssl.SSLContext] = []
    original = ssl.create_default_context

    def capture(
        *, cafile: str | None = None, capath: str | None = None, cadata: str | bytes | None = None
    ) -> ssl.SSLContext:
        calls.append(cafile)
        context = original(cafile=cafile, capath=capath, cadata=cadata)
        contexts.append(context)
        return context

    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "unknown-ca.pem"))
    monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path / "unknown-ca-dir"))
    monkeypatch.setattr(ssl, "create_default_context", capture)
    client = SparkHttpClient(
        settings=SparkSettings(
            history_server_url="https://history.example", cache_dir=str(tmp_path)
        ),
        secrets=SparkSecrets(),
    )
    try:
        client._ensure_client()
        assert calls and calls[0] is not None
        assert calls[0] != str(tmp_path / "unknown-ca.pem")
        assert contexts[0].cert_store_stats()["x509_ca"] > 0
    finally:
        await client.close()
