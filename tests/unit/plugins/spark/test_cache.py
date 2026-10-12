"""Private persistence and reuse through an actual mock HTTP download."""

# ruff: noqa: ASYNC240 -- tiny synthetic files for assertions
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from mcp_stdio.core.config import ConfigError
from mcp_stdio.plugins.spark.config import SparkSecrets, SparkSettings
from mcp_stdio.plugins.spark.gateway import SparkGatewayError
from tests.unit.plugins.spark.fixtures import APP, archive_bytes, encode, events
from tests.unit.plugins.spark.test_http_client import Stream


def _adapter(
    tmp_path: Path, transport: httpx.AsyncBaseTransport, source: str = "https://history.example"
):
    from mcp_stdio.plugins.spark.cache import SparkEventLogAdapter

    return SparkEventLogAdapter(
        settings=SparkSettings(history_server_url=source, cache_dir=str(tmp_path / "l3")),
        secrets=SparkSecrets(gateway_cookie=SecretStr("session=synthetic-cookie")),
        transport=transport,
    )


async def test_root_lock_permissions_restart_reuse_and_refresh(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, stream=Stream([archive_bytes()]))

    transport = httpx.MockTransport(handler)
    adapter = _adapter(tmp_path, transport)
    try:
        with pytest.raises(ConfigError):
            _adapter(tmp_path, transport)
        first = await adapter.download(APP, "1", deadline=time.monotonic() + 5)
        second = await adapter.download(APP, "1", deadline=time.monotonic() + 5)
        assert first.manifest_path != second.manifest_path
        assert (tmp_path / "l3").stat().st_mode & 0o777 == 0o700
        for result in (first, second):
            assert Path(result.manifest_path).is_file()
            assert Path(result.files[0].local_path).stat().st_mode & 0o777 == 0o600
            assert not list(Path(result.manifest_path).parent.glob("*.zip"))
        assert not list((tmp_path / "l3").glob(".part-*"))
    finally:
        await adapter.close()
        await adapter.close()
    adapter = _adapter(tmp_path, transport)
    try:
        hit = await adapter.lookup(APP, "1", deadline=time.monotonic() + 5)
        assert hit is not None and hit.cache_hit
        assert hit.manifest_path == second.manifest_path
        assert hit.downloaded_at == second.downloaded_at
        assert calls == 2
        assert await adapter.lookup(APP, None, deadline=time.monotonic() + 5) is None
    finally:
        await adapter.close()
    other = _adapter(tmp_path, transport, source="https://other.example")
    try:
        assert await other.lookup(APP, "1", deadline=time.monotonic() + 5) is None
    finally:
        await other.close()


@pytest.mark.parametrize("damage", ["bytes", "missing", "symlink", "manifest"])
async def test_corrupt_cache_never_served(tmp_path: Path, damage: str) -> None:
    adapter = _adapter(
        tmp_path,
        httpx.MockTransport(lambda request: httpx.Response(200, stream=Stream([archive_bytes()]))),
    )
    try:
        result = await adapter.download(APP, "1", deadline=time.monotonic() + 5)
        file = Path(result.files[0].local_path)
        if damage == "bytes":
            file.write_text("tampered")
        elif damage == "missing":
            file.unlink()
        elif damage == "symlink":
            file.unlink()
            file.symlink_to(tmp_path / "foreign")
        else:
            Path(result.manifest_path).write_text("{}")
        with pytest.raises(SparkGatewayError) as error:
            await adapter.lookup(APP, "1", deadline=time.monotonic() + 5)
        assert error.value.tool_error.category.value == "UNEXPECTED_RESPONSE"
    finally:
        await adapter.close()


async def test_failed_multi_member_download_has_no_partial_publish(tmp_path: Path) -> None:
    good = archive_bytes()
    bad = archive_bytes({APP + "_1": encode(events()), APP + "_2": b"invalid"})
    payloads = [good, bad]
    adapter = _adapter(
        tmp_path,
        httpx.MockTransport(lambda request: httpx.Response(200, stream=Stream([payloads.pop(0)]))),
    )
    try:
        first = await adapter.download(APP, "1", deadline=time.monotonic() + 5)
        with pytest.raises(SparkGatewayError):
            await adapter.download(APP, None, deadline=time.monotonic() + 5)
        assert Path(first.manifest_path).is_file()
        assert not list((tmp_path / "l3").glob(".part-*"))
        assert len(list((tmp_path / "l3").rglob("manifest.json"))) == 1
        manifest = json.loads(Path(first.manifest_path).read_text())
        assert manifest["format_version"] == 1
        assert manifest["history_server_url"] == "https://history.example"
        assert "cache_hit" not in manifest
    finally:
        await adapter.close()


async def test_cancelled_download_cleans_owned_staging(tmp_path: Path) -> None:
    stream = Stream([archive_bytes()], delay=1)
    adapter = _adapter(
        tmp_path, httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
    )
    try:
        task = asyncio.create_task(adapter.download(APP, "1", deadline=time.monotonic() + 5))
        await asyncio.sleep(0.03)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not list((tmp_path / "l3").glob(".part-*"))
        assert stream.closed
    finally:
        await adapter.close()


async def test_close_cancels_active_acquisition_before_releasing_root(tmp_path: Path) -> None:
    stream = Stream([archive_bytes()], delay=1)
    adapter = _adapter(
        tmp_path, httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
    )
    task = asyncio.create_task(adapter.download(APP, "1", deadline=time.monotonic() + 5))
    try:
        await asyncio.sleep(0.04)
        await adapter.close()
        assert task.done()
        assert stream.closed
        assert not list((tmp_path / "l3").glob(".part-*"))
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await adapter.close()
