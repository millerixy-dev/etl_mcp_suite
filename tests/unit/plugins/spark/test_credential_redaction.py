"""Secret source semantics and event-to-driver regressions with synthetic inputs."""

# ruff: noqa: ASYNC240 -- tiny synthetic evidence reads
from __future__ import annotations

import base64
import time
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from mcp_stdio.plugins.spark.cache import SparkEventLogAdapter
from mcp_stdio.plugins.spark.config import SparkSecrets
from mcp_stdio.plugins.spark.executor_logs import SparkExecutorLogAdapter
from mcp_stdio.plugins.spark.files import credential_values, redact_event
from tests.unit.plugins.spark.fixtures import APP, archive_bytes, encode, events
from tests.unit.plugins.spark.test_executor_logs import (
    JOB,
    ORIGINAL,
    ROOT,
    html_log,
    log_settings,
    request,
)
from tests.unit.plugins.spark.test_http_client import Stream


@pytest.mark.parametrize("opaque", ["opaque==", "name=value;part=tail", "opaque=value"])
def test_normalization_does_not_parse_opaque_secrets(opaque: str) -> None:
    values = credential_values((opaque, "", opaque))
    assert values == (opaque,)
    assert credential_values(values) == values
    assert redact_event({"detail": opaque}, values) == {"detail": "[REDACTED]"}


def test_basic_credentials_do_not_generate_fragments() -> None:
    secrets = SparkSecrets(username=SecretStr("demo"), password=SecretStr("password"))
    basic = base64.b64encode(b"demo:password").decode()
    assert basic.endswith("==")
    values = credential_values(secrets.redaction_values)
    assert set(values) == {"demo", "password", basic}
    assert redact_event({"detail": "left_id=right_id", "url": ORIGINAL}, values) == {
        "detail": "left_id=right_id",
        "url": ORIGINAL,
    }


def test_only_configured_cookie_header_is_split() -> None:
    header = 'sid="padded=="; other=second=value; empty='
    secrets = SparkSecrets(gateway_cookie=SecretStr(header))
    assert set(secrets.redaction_values) == {header, "padded==", "second=value"}
    values = credential_values(secrets.redaction_values)
    assert credential_values(values) == values
    assert redact_event({"detail": "padded== second=value x=y"}, values) == {
        "detail": "[REDACTED] [REDACTED] x=y"
    }


def test_actual_equals_password_is_still_redacted() -> None:
    secrets = SparkSecrets(username=SecretStr("demo"), password=SecretStr("="))
    assert redact_event({"detail": "x=y"}, credential_values(secrets.redaction_values)) == {
        "detail": "x[REDACTED]y"
    }


@pytest.mark.parametrize("auth_mode", ["basic", "cookie"])
async def test_event_to_driver_preserves_queries_and_redacts_secrets(
    tmp_path: Path, auth_mode: str
) -> None:
    settings = log_settings(tmp_path)
    if auth_mode == "basic":
        settings = settings.model_copy(update={"knox_sso_url": ROOT + "/sso"})
        secrets = SparkSecrets(username=SecretStr("demo"), password=SecretStr("password"))
    else:
        secrets = SparkSecrets(gateway_cookie=SecretStr('sid="configured=="; other=another'))
    acquired = "issued=="
    private = " ".join((*secrets.redaction_values, acquired))
    records = events("2")
    records[1]["Driver Logs"] = {"stdout": ORIGINAL}
    records.insert(2, {"Event": "DiagnosticText", "detail": private, "sql": "left_id=right_id"})
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        if req.method == "POST":
            return httpx.Response(303, headers={"set-cookie": f"jwt={acquired}; Path=/; Secure"})
        if "/sparkhistory/" in req.url.path:
            return httpx.Response(
                200,
                headers={"set-cookie": f"jwt={acquired}; Path=/; Secure"},
                stream=Stream([archive_bytes({APP + "_2": encode(records)})]),
            )
        assert req.url.params["start"] == "-65536"
        if "/node/containerlogs/" in req.url.path:
            return httpx.Response(
                307,
                headers={"location": JOB, "set-cookie": f"jwt={acquired}; Path=/; Secure"},
            )
        return httpx.Response(200, stream=Stream([html_log(private + "\nrows=42\nEOF")]))

    transport = httpx.MockTransport(handler)
    source = SparkEventLogAdapter(settings=settings, secrets=secrets, transport=transport)
    adapter = SparkExecutorLogAdapter(
        settings=settings, secrets=secrets, event_logs=source, transport=transport
    )
    try:
        result = await adapter.fetch(request(log_type="stdout"), deadline=time.monotonic() + 5)
        saved = Path(result.local_path).read_text()
        assert "rows=42\nEOF" in saved
        event_path = next(Path(settings.cache_dir).glob(f"{APP}/attempt-2/*/eventlog-0001.jsonl"))
        evidence = event_path.read_text()
        assert ORIGINAL in evidence and "left_id=right_id" in evidence
        for secret in (*secrets.redaction_values, acquired):
            assert secret not in saved and secret not in evidence
        assert any("/jobhistory/" in path for path in calls)
    finally:
        await adapter.close()
        await source.close()
