"""ZIP/event validation uses synthetic JSONL and archives."""
# ruff: noqa: ASYNC240 -- synchronous reads of tiny synthetic test files

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pytest

from mcp_stdio.plugins.spark.gateway import SparkGatewayError
from tests.unit.plugins.spark.fixtures import APP, archive_bytes, encode, events


async def _process(
    tmp_path: Path, members: dict[str, bytes], attempt: str | None = None, max_bytes: int = 1000000
):
    from mcp_stdio.plugins.spark.files import process_archive

    path = tmp_path / "source.zip"
    path.write_bytes(archive_bytes(members))
    out = tmp_path / "output"
    out.mkdir(exist_ok=True)
    return await process_archive(
        path,
        out,
        application_id=APP,
        attempt_id=attempt,
        max_bytes=max_bytes,
        deadline=time.monotonic() + 5,
    )


async def test_archive_single_all_null_attempt_identity(tmp_path: Path) -> None:
    data = encode(events())
    result = await _process(tmp_path, {APP + "_1": data}, attempt="1")
    assert result[0].attempt_id == "1"
    assert result[0].event_count == 3
    assert result[0].source_sha256 == hashlib.sha256(data).hexdigest()
    assert result[0].application_end_seen
    for file in (tmp_path / "output").iterdir():
        file.unlink()
    result = await _process(tmp_path, {APP: encode(events(None)), APP + "_2": encode(events("2"))})
    assert {file.attempt_id for file in result} == {None, "2"}


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "/absolute",
        "nested/file",
        APP + "_1.lz4",
        APP + "_1.snappy",
        "other_app",
    ],
)
async def test_archive_rejects_path_codec_and_identity(tmp_path: Path, name: str) -> None:
    with pytest.raises(SparkGatewayError) as error:
        await _process(tmp_path, {name: encode(events())})
    assert error.value.tool_error.category.value == "UNEXPECTED_RESPONSE"
    assert not (tmp_path.parent / "escape").exists()


@pytest.mark.parametrize(
    "kind",
    [
        "wrong_app",
        "wrong_attempt",
        "missing_start",
        "missing_logstart",
        "invalid_json",
        "invalid_utf8",
        "non_object",
        "missing_event",
        "bad_tail",
        "conflicting_start",
    ],
)
async def test_record_identity_errors(tmp_path: Path, kind: str) -> None:
    records = events()
    name = APP + "_1"
    if kind == "wrong_app":
        records = events(app="application_2_99")
    if kind == "wrong_attempt":
        records = events("2")
    if kind == "missing_start":
        records.pop(1)
    if kind == "missing_logstart":
        records.pop(0)
    if kind == "conflicting_start":
        records.append(events("2")[1])
    data = encode(records)
    extras = {
        "invalid_json": b"not-json\n",
        "invalid_utf8": b"\xff\n",
        "non_object": b"[]\n",
        "missing_event": b"{}\n",
        "bad_tail": b'{"Event":',
    }
    if kind in extras:
        data += extras[kind]
    if kind == "bad_tail":
        name += ".inprogress"
    with pytest.raises(SparkGatewayError) as error:
        await _process(tmp_path, {name: data}, attempt="1")
    assert error.value.tool_error.category.value == "UNEXPECTED_RESPONSE"


async def test_record_no_end_is_valid_and_patch_version_not_gated(tmp_path: Path) -> None:
    records = events()[:2]
    records[0]["Spark Version"] = "2.4.8"
    result = await _process(tmp_path, {APP + "_1.inprogress": encode(records).rstrip(b"\n")})
    assert result[0].application_end_seen is False
    assert result[0].spark_version == "2.4.8"


async def test_archive_actual_expanded_limit(tmp_path: Path) -> None:
    with pytest.raises(SparkGatewayError) as error:
        await _process(tmp_path, {APP + "_1": encode(events())}, max_bytes=10)
    assert error.value.tool_error.category.value == "UPSTREAM_ERROR"


async def test_archive_crc_corruption(tmp_path: Path) -> None:
    from mcp_stdio.plugins.spark.files import process_archive

    payload = bytearray(archive_bytes())
    offset = payload.index(b"SparkListenerLogStart")
    payload[offset] ^= 1
    path = tmp_path / "bad.zip"
    path.write_bytes(payload)
    with pytest.raises(SparkGatewayError) as error:
        await process_archive(
            path,
            tmp_path,
            application_id=APP,
            attempt_id=None,
            max_bytes=1000000,
            deadline=time.monotonic() + 5,
        )
    assert error.value.tool_error.category.value == "UNEXPECTED_RESPONSE"


@pytest.mark.parametrize(
    "secret_shape",
    [
        {"password": "sensitive-sentinel"},
        {"nested": {"access_key": "sensitive-sentinel"}},
        {"detail": "https://user:sensitive-sentinel@service.example/?token=second-sentinel"},
        {"detail": "authorization: Bearer sensitive-sentinel"},
        {"detail": "password='sensitive-sentinel'"},
        {"sensitive-sentinel": "value"},
        {"detail": "ordinary text sensitive-sentinel"},
    ],
)
async def test_redact_nested_strings_and_credentials(
    tmp_path: Path, secret_shape: dict[str, object]
) -> None:
    import json

    from mcp_stdio.plugins.spark.files import process_archive

    records = events()
    records.insert(
        2, {"Event": "SparkListenerTaskEnd", "Metrics": {"duration": 123}, **secret_shape}
    )
    data = encode(records)
    archive = tmp_path / "source.zip"
    archive.write_bytes(archive_bytes({APP + "_1": data}))
    result = await process_archive(
        archive,
        tmp_path,
        application_id=APP,
        attempt_id="1",
        max_bytes=1000000,
        deadline=time.monotonic() + 5,
        secret_values=("session=sensitive-sentinel",),
    )
    saved = Path(result[0].local_path).read_bytes()
    assert b"sensitive-sentinel" not in saved
    assert b"second-sentinel" not in saved
    assert result[0].source_sha256 == hashlib.sha256(data).hexdigest()
    assert result[0].sha256 == hashlib.sha256(saved).hexdigest()
    assert result[0].sha256 != result[0].source_sha256
    task = json.loads(saved.splitlines()[2])
    assert task["Metrics"]["duration"] == 123
    assert result[0].event_count == 4


async def test_redact_environment_allowlist_and_digest(tmp_path: Path) -> None:
    import json

    records = events()
    records.insert(
        2,
        {
            "Event": "SparkListenerEnvironmentUpdate",
            "Spark Properties": {
                "spark.executor.memory": "4g",
                "spark.my.custom": "env-secret",
                "spark.password": "env-secret",
            },
            "System Properties": {"java.secret": "env-secret"},
            "Classpath Entries": {"environment-path": "env-secret"},
        },
    )
    result = await _process(tmp_path, {APP + "_1": encode(records)})
    saved = Path(result[0].local_path).read_text()
    assert "env-secret" not in saved
    env = json.loads(saved.splitlines()[2])
    assert env["Spark Properties"]["spark.executor.memory"] == "4g"
    assert env["Spark Properties"]["spark.my.custom"] == "[REDACTED]"


async def test_redact_complete_unknown_cookie_header(tmp_path: Path) -> None:
    records = events()
    records.insert(
        2,
        {
            "Event": "SparkListenerTaskEnd",
            "detail": "Cookie: sid=unknown-cookie-one; auth_ticket=unknown-cookie-two",
        },
    )
    result = await _process(tmp_path, {APP + "_1": encode(records)})
    saved = Path(result[0].local_path).read_text()
    assert "unknown-cookie-one" not in saved
    assert "unknown-cookie-two" not in saved


async def test_acquire_large_record_within_total_budget(tmp_path: Path) -> None:
    records = events()
    records.insert(
        2, {"Event": "VendorLargeEvent", "payload": "node " * (8 * 1024 * 1024 // 5 + 1)}
    )
    data = encode(records)
    result = await _process(tmp_path, {APP + "_1": data}, max_bytes=len(data))
    saved = Path(result[0].local_path).read_bytes()
    assert saved == data
    assert result[0].event_count == 4
    assert result[0].source_sha256 == hashlib.sha256(data).hexdigest()
    assert result[0].sha256 == hashlib.sha256(saved).hexdigest()


@pytest.mark.parametrize("final_newline", [True, False])
async def test_acquire_exact_output_budget(tmp_path: Path, final_newline: bool) -> None:
    output = encode(events())
    source = output if final_newline else output.rstrip(b"\n")
    result = await _process(tmp_path, {APP + "_1": source}, max_bytes=len(output))
    assert Path(result[0].local_path).read_bytes() == output
    assert result[0].source_sha256 == hashlib.sha256(source).hexdigest()


async def test_acquire_total_source_overflow_across_members(tmp_path: Path) -> None:
    first, second = encode(events("1")), encode(events("2"))
    with pytest.raises(SparkGatewayError) as error:
        await _process(
            tmp_path,
            {APP + "_1": first, APP + "_2": second},
            max_bytes=len(first) + len(second) - 1,
        )
    assert error.value.tool_error.category.value == "UPSTREAM_ERROR"


async def test_acquire_checks_remaining_budget_before_parsing(tmp_path: Path) -> None:
    prefix = encode(events()[:2])
    with pytest.raises(SparkGatewayError) as error:
        await _process(tmp_path, {APP + "_1": prefix + b"x" * 100}, max_bytes=len(prefix) + 1)
    assert error.value.tool_error.category.value == "UPSTREAM_ERROR"


async def test_acquire_total_output_overflow_after_redaction(tmp_path: Path) -> None:
    records = events()
    records.insert(2, {"Event": "VendorEvent", "password": "x"})
    data = encode(records)
    assert len(data.replace(b'"x"', b'"[REDACTED]"')) > len(data)
    with pytest.raises(SparkGatewayError) as error:
        await _process(tmp_path, {APP + "_1": data}, max_bytes=len(data))
    assert error.value.tool_error.category.value == "UPSTREAM_ERROR"
