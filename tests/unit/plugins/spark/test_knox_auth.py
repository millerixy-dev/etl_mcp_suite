"""Knox Basic exchange contracts; every credential is synthetic."""

# pyright: reportPrivateUsage=false
# ruff: noqa: ASYNC240 -- tiny synthetic evidence assertions
from __future__ import annotations

import asyncio
import base64
import time
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from mcp_stdio.core.config import ConfigError
from mcp_stdio.plugins.spark.cache import SparkEventLogAdapter
from mcp_stdio.plugins.spark.config import SparkSecrets, SparkSettings
from mcp_stdio.plugins.spark.gateway import SparkGatewayError
from mcp_stdio.plugins.spark.http_client import SparkHttpClient
from mcp_stdio.plugins.spark.plugin import PLUGIN_DEFINITION
from tests.unit.plugins.spark.fixtures import APP, archive_bytes, encode, events
from tests.unit.plugins.spark.test_http_client import Stream

USER = "synthetic-user"
PASSWORD = "synthetic-password"
TOKEN = "synthetic-issued-token"
BASIC = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
SSO = "https://history.example/gateway/knoxsso/api/v1/websso"


def settings(tmp_path: Path) -> SparkSettings:
    return SparkSettings(
        history_server_url="https://history.example/gateway/sparkhistory",
        cache_dir=str(tmp_path / "l3"),
        knox_sso_url=SSO,
    )


def secrets() -> SparkSecrets:
    return SparkSecrets(username=SecretStr(USER), password=SecretStr(PASSWORD))


@pytest.mark.parametrize("status", [200, 204, 302, 303, 307, 308])
async def test_basic_exchange_scopes_headers_and_discards_cookies(tmp_path: Path, status: int):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "POST":
            assert str(request.url).split("?")[0] == SSO
            assert (
                request.url.params["originalUrl"] == "https://history.example/gateway/sparkhistory/"
            )
            assert request.headers["Authorization"] == "Basic " + BASIC
            assert request.content == b""
            assert "Cookie" not in request.headers
            return httpx.Response(
                status,
                headers={
                    "Set-Cookie": f"hadoop-jwt={TOKEN}; Path=/; Secure",
                    "Location": "https://foreign.example/ignored",
                },
            )
        assert "Authorization" not in request.headers
        assert request.headers["Cookie"] == f"hadoop-jwt={TOKEN}"
        return httpx.Response(200, stream=Stream([archive_bytes()]))

    client = SparkHttpClient(
        settings=settings(tmp_path), secrets=secrets(), transport=httpx.MockTransport(handler)
    )
    try:
        for index in range(2):
            values = await client.receive(
                APP, "1", tmp_path / f"{index}.zip", deadline=time.monotonic() + 3
            )
            assert TOKEN in values
            assert not client._ensure_client().cookies
        assert [request.method for request in calls] == ["POST", "GET", "POST", "GET"]
    finally:
        await client.close()


@pytest.mark.parametrize(
    "status,cookie,category",
    [
        (401, f"hadoop-jwt={TOKEN}; Path=/", "AUTHENTICATION_FAILED"),
        (403, "", "PERMISSION_DENIED"),
        (429, "", "UPSTREAM_ERROR"),
        (500, "", "UPSTREAM_ERROR"),
        (200, "", "AUTHENTICATION_FAILED"),
        (302, f"jwt={TOKEN}; Domain=foreign.example; Path=/", "AUTHENTICATION_FAILED"),
        (200, f"jwt={TOKEN}; Path=/other", "AUTHENTICATION_FAILED"),
    ],
)
async def test_failed_login_never_downloads_or_retains_cookies(
    tmp_path: Path, status: int, cookie: str, category: str
):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, headers={"Set-Cookie": cookie})

    client = SparkHttpClient(
        settings=settings(tmp_path), secrets=secrets(), transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(SparkGatewayError) as error:
            await client.receive(APP, "1", tmp_path / "archive", deadline=time.monotonic() + 3)
        assert error.value.tool_error.category.value == category
        assert len(calls) == 1
        assert not client._ensure_client().cookies
        assert not (tmp_path / "archive").exists()
        assert PASSWORD not in str(error.value) and TOKEN not in str(error.value)
    finally:
        await client.close()


@pytest.mark.parametrize("cancel", [False, True])
async def test_login_deadline_and_cancellation(tmp_path: Path, cancel: bool):
    entered = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        entered.set()
        await asyncio.sleep(10)
        return httpx.Response(200)

    client = SparkHttpClient(
        settings=settings(tmp_path), secrets=secrets(), transport=httpx.MockTransport(handler)
    )
    try:
        task = asyncio.create_task(
            client.receive(
                APP, "1", tmp_path / "archive", deadline=time.monotonic() + (3 if cancel else 0.03)
            )
        )
        await entered.wait()
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(SparkGatewayError) as error:
                await task
            assert error.value.tool_error.category.value == "TIMEOUT"
        assert not client._ensure_client().cookies
        assert not (tmp_path / "archive").exists()
    finally:
        await client.close()


async def test_auth_secrets_are_redacted_from_evidence_and_cache_skips_login(tmp_path: Path):
    records = events()
    records.append({"Event": "Custom", "detail": f"{USER} {PASSWORD} {BASIC} {TOKEN}"})
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "POST":
            return httpx.Response(
                200, headers={"Set-Cookie": f"hadoop-jwt={TOKEN}; Path=/; Secure"}
            )
        return httpx.Response(200, stream=Stream([archive_bytes({APP + "_1": encode(records)})]))

    adapter = SparkEventLogAdapter(
        settings=settings(tmp_path), secrets=secrets(), transport=httpx.MockTransport(handler)
    )
    try:
        result = await adapter.download(APP, "1", deadline=time.monotonic() + 5)
        saved = (
            Path(result.files[0].local_path).read_text()
            + Path(result.manifest_path).read_text()
            + result.model_dump_json()
        )
        for value in (USER, PASSWORD, BASIC, TOKEN):
            assert value not in saved
        hit = await adapter.lookup(APP, "1", deadline=time.monotonic() + 5)
        assert hit is not None and hit.cache_hit
        assert calls == ["POST", "GET"]
    finally:
        await adapter.close()


@pytest.mark.parametrize(
    "overrides",
    [
        {"SPARK_USERNAME": ""},
        {"SPARK_PASSWORD": ""},
        {"SPARK_KNOX_SSO_URL": ""},
        {"SPARK_KNOX_SSO_URL": "https://foreign.example/api/v1/websso"},
        {"SPARK_KNOX_SSO_URL": "http://history.example/api/v1/websso"},
        {"SPARK_GATEWAY_COOKIE": "session=synthetic-cookie"},
        {"SPARK_USERNAME": "invalid:name"},
        {"SPARK_PASSWORD": "bad\nvalue"},
    ],
)
def test_bad_auth_configuration_is_local_and_safe(tmp_path: Path, overrides: dict[str, str]):
    env = {
        "SPARK_HISTORY_SERVER_URL": "https://history.example/gateway/sparkhistory",
        "SPARK_CACHE_DIR": str(tmp_path / "l3"),
        "SPARK_KNOX_SSO_URL": SSO,
        "SPARK_USERNAME": USER,
        "SPARK_PASSWORD": PASSWORD,
        **overrides,
    }
    with pytest.raises(ConfigError) as error:
        PLUGIN_DEFINITION.create_runtime(None, environ=env)
    assert PASSWORD not in str(error.value)
    assert not (tmp_path / "l3" / ".lock").exists()


async def test_basic_startup_is_lazy_and_redacts_credentials(tmp_path: Path):
    runtime = PLUGIN_DEFINITION.create_runtime(
        None,
        environ={
            "SPARK_HISTORY_SERVER_URL": "https://history.example/gateway/sparkhistory",
            "SPARK_CACHE_DIR": str(tmp_path / "l3"),
            "SPARK_KNOX_SSO_URL": SSO,
            "SPARK_USERNAME": USER,
            "SPARK_PASSWORD": PASSWORD,
        },
    )
    try:
        assert all(value in runtime.redaction_values for value in (USER, PASSWORD, BASIC))
    finally:
        await runtime.close()
