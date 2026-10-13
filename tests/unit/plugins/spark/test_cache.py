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


async def test_reader_selects_explicit_null_and_only_scans_selected_file(tmp_path: Path) -> None:
    from mcp_stdio.plugins.spark import inspection_reader
    from mcp_stdio.plugins.spark.inspection_models import InspectRequest
    from tests.unit.plugins.spark.fixtures import private_manifest

    manifest, body = private_manifest(tmp_path / "l3")
    Path(body["files"][1]["local_path"]).unlink()
    seen: list[int] = []
    result = await inspection_reader.VerifiedEventLogReader(
        SparkSettings(history_server_url="https://history.example", cache_dir=str(tmp_path / "l3"))
    ).read(
        InspectRequest(manifest_path=str(manifest), attempt_id=None),
        lambda line, event: seen.append(line),
        deadline=time.monotonic() + 5,
    )
    assert result.snapshot.attempt_id is None
    assert result.snapshot.application_id == APP
    assert result.event_count == 3 and seen == [1, 2, 3]
    assert result.coverage.application_end_seen


@pytest.mark.parametrize(
    "damage",
    [
        "source",
        "format",
        "hash",
        "count",
        "identity",
        "version",
        "ending",
        "path",
        "manifest_path",
        "tail",
        "missing",
        "symlink",
        "parent_symlink",
        "attempt",
        "size",
        "deadline",
    ],
)
async def test_reader_rejects_corrupt_explicit_snapshot(tmp_path: Path, damage: str) -> None:
    from mcp_stdio.plugins.spark import inspection_reader
    from mcp_stdio.plugins.spark.inspection_models import InspectRequest
    from tests.unit.plugins.spark.fixtures import private_manifest

    manifest, body = private_manifest(tmp_path / "l3", ("1",))
    item = body["files"][0]
    path = Path(item["local_path"])
    if damage == "source":
        body["history_server_url"] = "https://foreign.example"
    elif damage == "format":
        body["format_version"] = True
    elif damage == "hash":
        item["sha256"] = "a" * 64
    elif damage == "count":
        item["event_count"] = 4
    elif damage == "identity":
        body["application_id"] = "application_2_3"
    elif damage == "version":
        item["spark_version"] = "3.0"
    elif damage == "ending":
        item["application_end_seen"] = False
    elif damage == "path":
        item["local_path"] = str(tmp_path / "outside.jsonl")
    elif damage == "manifest_path":
        body["manifest_path"] = str(tmp_path / "manifest.json")
    elif damage == "tail":
        path.write_bytes(path.read_bytes() + b'{"Event":"match"}\nNaN\n')
    elif damage == "missing":
        path.unlink()
    elif damage == "symlink":
        path.unlink()
        path.symlink_to(tmp_path / "absent")
    elif damage == "parent_symlink":
        original = manifest.parent
        target = original.with_name("b" * 32)
        original.rename(target)
        original.symlink_to(target, target_is_directory=True)
    manifest.write_text(json.dumps(body))
    reader = inspection_reader.VerifiedEventLogReader(
        SparkSettings(
            history_server_url="https://history.example",
            cache_dir=str(tmp_path / "l3"),
            max_bytes=1 if damage == "size" else 268435456,
        )
    )
    with pytest.raises(SparkGatewayError) as error:
        await reader.read(
            InspectRequest(
                manifest_path=str(manifest), attempt_id="2" if damage == "attempt" else "1"
            ),
            lambda line, event: None,
            deadline=time.monotonic() + (-1 if damage == "deadline" else 5),
        )
    expected = (
        "NOT_FOUND"
        if damage in {"missing", "attempt"}
        else ("TIMEOUT" if damage == "deadline" else "UNEXPECTED_RESPONSE")
    )
    assert error.value.tool_error.category.value == expected


@pytest.mark.parametrize("value", [True, -1, 2**63, "١", "-1", "1.0", " 1", "9" * 100])
def test_direct_ids_reject_invalid_numeric_properties(value: object) -> None:
    from mcp_stdio.plugins.spark.inspection_events import direct_ids

    ids = direct_ids(
        {
            "Event": "SparkListenerJobStart",
            "Properties": {"spark.sql.execution.id": value},
            "Stage IDs": [3],
        }
    )
    assert ids.execution_id is None and ids.stage_id is None


def test_direct_ids_own_fields_only() -> None:
    from mcp_stdio.plugins.spark.inspection_events import direct_ids

    ids = direct_ids(
        {
            "Event": "SparkListenerTaskEnd",
            "Stage ID": 3,
            "Stage Attempt ID": 1,
            "Task Info": {"Task ID": 7, "Executor ID": "4"},
        }
    )
    assert (ids.stage_id, ids.stage_attempt_id, ids.task_id, ids.executor_id) == (3, 1, 7, "4")
    assert ids.execution_id is None and ids.job_id is None
    assert (
        direct_ids(
            {"Event": "SparkListenerJobStart", "Properties": {"spark.sql.execution.id": "012"}}
        ).execution_id
        == 12
    )


@pytest.mark.parametrize(
    "raw",
    [
        b'{"Event":"Vendor","value":1e400}\n',
        b'{"Event":"Vendor","value":NaN}\n',
        b"[]\n",
        b'{"Event":true}\n',
        b'{"Event":"bad\\nname"}\n',
        b"broken\n",
    ],
)
async def test_reader_validates_tail_after_visitor_matches(tmp_path: Path, raw: bytes) -> None:
    import hashlib

    from mcp_stdio.plugins.spark.inspection_models import InspectRequest
    from mcp_stdio.plugins.spark.inspection_reader import VerifiedEventLogReader
    from tests.unit.plugins.spark.fixtures import private_manifest

    manifest, body = private_manifest(tmp_path / "l3", (None,))
    item = body["files"][0]
    path = Path(item["local_path"])
    payload = path.read_bytes() + raw
    path.write_bytes(payload)
    item.update(size_bytes=len(payload), event_count=4, sha256=hashlib.sha256(payload).hexdigest())
    manifest.write_text(json.dumps(body))
    with pytest.raises(SparkGatewayError) as error:
        await VerifiedEventLogReader(
            SparkSettings(
                history_server_url="https://history.example", cache_dir=str(tmp_path / "l3")
            )
        ).read(
            InspectRequest(manifest_path=str(manifest), attempt_id=None),
            lambda line, event: None,
            deadline=time.monotonic() + 5,
        )
    assert error.value.tool_error.category.value == "UNEXPECTED_RESPONSE"


async def test_reader_single_event_open_and_cancel_closes_descriptors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from mcp_stdio.plugins.spark.inspection_models import InspectRequest
    from mcp_stdio.plugins.spark.inspection_reader import VerifiedEventLogReader
    from tests.unit.plugins.spark.fixtures import private_manifest

    manifest, _ = private_manifest(tmp_path / "l3", (None,))
    original = os.open
    opened: list[tuple[str, int]] = []

    def track(path: str | Path, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        fd = original(path, flags, mode, dir_fd=dir_fd)
        opened.append((str(path), fd))
        return fd

    monkeypatch.setattr(os, "open", track)
    reader = VerifiedEventLogReader(
        SparkSettings(history_server_url="https://history.example", cache_dir=str(tmp_path / "l3"))
    )
    request = InspectRequest(manifest_path=str(manifest), attempt_id=None)
    await reader.read(request, lambda line, event: None, deadline=time.monotonic() + 5)
    assert len([name for name, _fd in opened if name.endswith(".jsonl")]) == 1
    for _name, fd in opened:
        with pytest.raises(OSError):
            os.fstat(fd)
    opened.clear()

    def cancel(line: int, event: dict[str, object]) -> None:
        current = asyncio.current_task()
        assert current is not None
        current.cancel()

    task = asyncio.create_task(reader.read(request, cancel, deadline=time.monotonic() + 5))
    with pytest.raises(asyncio.CancelledError):
        await task
    for _name, fd in opened:
        with pytest.raises(OSError):
            os.fstat(fd)


async def test_reader_query_requires_sanitized_digest(tmp_path: Path) -> None:
    from mcp_stdio.plugins.spark.inspection_models import QueryRequest
    from mcp_stdio.plugins.spark.inspection_reader import VerifiedEventLogReader
    from tests.unit.plugins.spark.fixtures import private_manifest

    manifest, _ = private_manifest(tmp_path / "l3", (None,))
    with pytest.raises(SparkGatewayError) as error:
        await VerifiedEventLogReader(
            SparkSettings(
                history_server_url="https://history.example", cache_dir=str(tmp_path / "l3")
            )
        ).read(
            QueryRequest(manifest_path=str(manifest), attempt_id=None, expected_sha256="b" * 64),
            lambda line, event: None,
            deadline=time.monotonic() + 5,
        )
    assert error.value.tool_error.category.value == "UNEXPECTED_RESPONSE"


async def test_reader_accepts_configured_ancestor_alias_with_canonical_manifest(
    tmp_path: Path,
) -> None:
    from mcp_stdio.plugins.spark.inspection_models import InspectRequest
    from mcp_stdio.plugins.spark.inspection_reader import VerifiedEventLogReader
    from tests.unit.plugins.spark.fixtures import private_manifest

    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    manifest, _ = private_manifest(real / "l3", (None,))
    scan = await VerifiedEventLogReader(
        SparkSettings(history_server_url="https://history.example", cache_dir=str(alias / "l3"))
    ).read(
        InspectRequest(manifest_path=str(manifest), attempt_id=None),
        lambda line, event: None,
        deadline=time.monotonic() + 5,
    )
    assert scan.event_count == 3


@pytest.mark.parametrize("target", ["root", "directory", "manifest", "event"])
async def test_reader_rejects_nonprivate_evidence(tmp_path: Path, target: str) -> None:
    from mcp_stdio.plugins.spark.inspection_models import InspectRequest
    from mcp_stdio.plugins.spark.inspection_reader import VerifiedEventLogReader
    from tests.unit.plugins.spark.fixtures import private_manifest

    root = tmp_path / "l3"
    manifest, body = private_manifest(root, (None,))
    path = {
        "root": root,
        "directory": manifest.parent,
        "manifest": manifest,
        "event": Path(body["files"][0]["local_path"]),
    }[target]
    path.chmod(0o755 if path.is_dir() else 0o644)
    with pytest.raises(SparkGatewayError) as error:
        await VerifiedEventLogReader(
            SparkSettings(history_server_url="https://history.example", cache_dir=str(root))
        ).read(
            InspectRequest(manifest_path=str(manifest), attempt_id=None),
            lambda line, event: None,
            deadline=time.monotonic() + 5,
        )
    assert error.value.tool_error.category.value == "UNEXPECTED_RESPONSE"
