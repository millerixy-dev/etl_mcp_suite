"""Synthetic executor-log contracts and acquisition tests; no cluster data."""

# pyright: reportPrivateUsage=false
# ruff: noqa: ASYNC240 -- tiny synthetic private evidence assertions
from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from mcp_stdio.core.errors import ErrorCategory
from mcp_stdio.plugins.spark.config import SparkSettings
from mcp_stdio.plugins.spark.executor_log_models import (
    SparkExecutorLogFetchResult,
    SparkExecutorLogRequest,
)
from mcp_stdio.plugins.spark.gateway import SparkGatewayError, spark_error
from tests.unit.plugins.spark.test_service import FakeGateway


def request(**extra: object) -> SparkExecutorLogRequest:
    from mcp_stdio.plugins.spark.executor_log_models import SparkExecutorLogRequest

    return SparkExecutorLogRequest.model_validate(
        {"application_id": "application_1_42", "attempt_id": "2", "executor_id": "driver", **extra}
    )


def log_result() -> SparkExecutorLogFetchResult:
    from mcp_stdio.plugins.spark.executor_log_models import SparkExecutorLogFetchResult

    return SparkExecutorLogFetchResult(
        application_id="application_1_42",
        attempt_id="2",
        executor_id="driver",
        container_id="container_e83_1_0042_02_000001",
        log_type="stderr",
        requested_tail_bytes=65536,
        fetched_at="2026-10-14T00:00:00Z",
        coverage="complete",
        local_path="/l3/stderr.log",
        size_bytes=0,
        sha256="a" * 64,
        manifest_path="/l3/manifest.json",
    )


def test_contract_defaults_and_exact_result() -> None:
    value = request()
    assert value.log_type == "stderr" and value.tail_bytes == 65536
    assert len(log_result().model_dump()) == 12


@pytest.mark.parametrize(
    "extra",
    [
        {"application_id": "application_１_42"},
        {"attempt_id": None},
        {"attempt_id": "02"},
        {"attempt_id": "0"},
        {"executor_id": "01"},
        {"executor_id": "../1"},
        {"tail_bytes": True},
        {"tail_bytes": "1"},
        {"tail_bytes": 0},
        {"tail_bytes": 1048577},
        {"log_type": "syslog"},
        {"url": "private"},
    ],
)
def test_strict_request_rejects_unsafe_inputs(extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        request(**extra)


class FakeLogGateway:
    def __init__(self, delay: float = 0, fail: bool = False) -> None:
        self.delay, self.fail = delay, fail
        self.calls: list[tuple[SparkExecutorLogRequest, float]] = []
        self.cleaned = False

    async def fetch(
        self, request: SparkExecutorLogRequest, *, deadline: float
    ) -> SparkExecutorLogFetchResult:
        self.calls.append((request, deadline))
        try:
            await asyncio.sleep(self.delay)
            if self.fail:
                raise spark_error(ErrorCategory.NOT_FOUND)
            return log_result()
        finally:
            self.cleaned = True

    async def close(self) -> None:
        self.cleaned = True


async def test_service_validation_success_and_error_remapping() -> None:
    from mcp_stdio.plugins.spark.service import SparkExecutorLogService

    gateway = FakeLogGateway()
    service = SparkExecutorLogService(gateway=gateway, request_timeout_seconds=1)
    before = time.monotonic()
    assert await service.fetch("application_1_42", "2", "driver") == log_result()
    assert before + 1 <= gateway.calls[0][1] <= time.monotonic() + 1
    for extra in ({"tail_bytes": True}, {"unexpected": "private"}):
        with pytest.raises(SparkGatewayError) as error:
            await service.fetch("application_1_42", "2", "driver", **extra)
        assert error.value.tool_error.category == ErrorCategory.INVALID_INPUT
    assert len(gateway.calls) == 1
    gateway.fail = True
    with pytest.raises(SparkGatewayError) as error:
        await service.fetch("application_1_42", "2", "driver")
    assert error.value.tool_error.operation.value == "fetch_spark_executor_log"
    assert error.value.tool_error.identifiers == {
        "application_id": "application_1_42",
        "attempt_id": "2",
        "executor_id": "driver",
        "log_type": "stderr",
    }


async def test_service_timeout_and_cancellation_cleanup() -> None:
    from mcp_stdio.plugins.spark.service import SparkExecutorLogService

    gateway = FakeLogGateway(delay=1)
    service = SparkExecutorLogService(gateway=gateway, request_timeout_seconds=0.01)
    with pytest.raises(SparkGatewayError) as error:
        await service.fetch("application_1_42", "2", "driver")
    assert error.value.tool_error.category == ErrorCategory.TIMEOUT
    assert gateway.cleaned
    gateway.cleaned = False
    task = asyncio.create_task(
        SparkExecutorLogService(gateway=gateway, request_timeout_seconds=2).fetch(
            "application_1_42", "2", "driver"
        )
    )
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert gateway.cleaned


# All URLs, HTML and credentials below are synthetic.
CONTAINER = "container_e83_1_0042_02_000001"
ROOT = "https://history.example/gateway/test"
ORIGINAL = f"http://node.nodes.example:8042/node/containerlogs/{CONTAINER}/owner/stdout?start=-4096"
JOB = (
    f"{ROOT}/jobhistory/joblogs/node.nodes.example:8041/{CONTAINER}/"
    f"{CONTAINER}/owner/stdout?scheme=http&host=jhs.example&port=19888"
)


def log_settings(tmp_path: Path) -> SparkSettings:
    from mcp_stdio.plugins.spark.config import SparkSettings

    return SparkSettings(
        history_server_url=ROOT + "/sparkhistory",
        cache_dir=str(tmp_path / "l3"),
        executor_log_node_manager_path="/yarn/nodemanager/node",
        executor_log_allowed_upstreams=[
            "http://*.nodes.example:8042",
            "http://jhs.example:19888",
            "http://other.example:19888",
        ],
    )


def html_log(
    text: str = "final line without newline", stream: str = "stdout", length: int | None = None
) -> bytes:
    from html import escape

    total = len(text.encode()) if length is None else length
    return (
        f"<html><pre>\n\n</pre><p>Log Type: {stream}</p>"
        f"<p>Log Length: {total}</p><pre>{escape(text)}</pre></html>"
    ).encode()


def test_route_maps_original_and_learns_jobhistory(tmp_path: Path) -> None:
    from mcp_stdio.plugins.spark.executor_logs import _LogRoute

    route = _LogRoute(log_settings(tmp_path), request(log_type="stdout"), ORIGINAL)
    assert route.url.startswith(ROOT + "/yarn/nodemanager/node/containerlogs/")
    assert "start=-65536" in route.url and "port=8042" in route.url
    target = route.redirect(route.url, JOB)
    assert ":8041/" in target and "start=-65536" in target
    with pytest.raises(SparkGatewayError):
        route.redirect(target, JOB.replace("host=jhs.example", "host=other.example"))


@pytest.mark.parametrize(
    "old,new",
    [
        ("history.example", "foreign.example"),
        (CONTAINER, "container_e83_1_0042_01_000001"),
        ("/owner/", "/other/"),
        ("/stdout?", "/stderr?"),
        ("node.nodes.example:8041", "other.nodes.example:8041"),
        ("host=jhs.example", "host=evil.example"),
        ("19888", "19888&host=jhs.example"),
        ("19888", "19888&end=1"),
        ("/owner/", "/%252f/"),
        ("19888", "19888#fragment"),
    ],
)
def test_reject_unsafe_redirect_before_request(tmp_path: Path, old: str, new: str) -> None:
    from mcp_stdio.plugins.spark.executor_logs import _LogRoute

    route = _LogRoute(log_settings(tmp_path), request(log_type="stdout"), ORIGINAL)
    with pytest.raises(SparkGatewayError) as error:
        route.redirect(route.url, JOB.replace(old, new))
    assert error.value.tool_error.category == ErrorCategory.UNEXPECTED_RESPONSE


def test_reject_login_and_wrong_original_container(tmp_path: Path) -> None:
    from mcp_stdio.plugins.spark.executor_logs import _LogRoute

    route = _LogRoute(log_settings(tmp_path), request(log_type="stdout"), ORIGINAL)
    with pytest.raises(SparkGatewayError) as error:
        route.redirect(route.url, ROOT + "/login")
    assert error.value.tool_error.category == ErrorCategory.AUTHENTICATION_FAILED
    for original in (
        ORIGINAL.replace("02_000001", "01_000001"),
        ORIGINAL + "&bad=1",
        ORIGINAL.replace("node.nodes.example", "multi.node.nodes.example"),
    ):
        with pytest.raises(SparkGatewayError):
            _LogRoute(log_settings(tmp_path), request(log_type="stdout"), original)


def test_html_stream_metadata_entities_empty_and_eof() -> None:
    from mcp_stdio.plugins.spark.executor_logs import parse_log_html

    parsed = parse_log_html(html_log("a<&\nEOF"), "stdout", CONTAINER)
    assert parsed.text == "a<&\nEOF" and parsed.coverage == "complete"
    assert parse_log_html(html_log(""), "stdout", CONTAINER).text == ""
    unknown = b"<p>Log Type: stdout</p><pre>EOF</pre>"
    assert parse_log_html(unknown, "stdout", CONTAINER).coverage == "unknown"
    assert parse_log_html(html_log("EOF", length=1000), "stdout", CONTAINER).coverage == "tail"


@pytest.mark.parametrize(
    "raw,category",
    [
        (b'<form><input type="password"></form>', "AUTHENTICATION_FAILED"),
        (b"<h1>User is not authorized to view the logs</h1>", "PERMISSION_DENIED"),
        (b"<h1>Logs not available for container</h1>", "NOT_FOUND"),
        (b"<pre>arbitrary</pre>", "UNEXPECTED_RESPONSE"),
        (html_log() + html_log(), "UNEXPECTED_RESPONSE"),
        (html_log(stream="stderr"), "UNEXPECTED_RESPONSE"),
        (html_log() + b"\xff", "UNEXPECTED_RESPONSE"),
        (b"<h1>container_e83_1_0042_01_000001</h1>" + html_log(), "UNEXPECTED_RESPONSE"),
    ],
)
def test_html_errors_are_not_success(raw: bytes, category: str) -> None:
    from mcp_stdio.plugins.spark.executor_logs import parse_log_html

    with pytest.raises(SparkGatewayError) as error:
        parse_log_html(raw, "stdout", CONTAINER)
    assert error.value.tool_error.category.value == category


async def test_controlled_network_auth_and_redaction(tmp_path: Path) -> None:
    import httpx
    from pydantic import SecretStr

    from mcp_stdio.plugins.spark.config import SparkSecrets
    from mcp_stdio.plugins.spark.executor_logs import SparkExecutorLogAdapter, _LogRoute
    from tests.unit.plugins.spark.test_http_client import Stream

    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if req.method == "POST":
            assert "Authorization" in req.headers
            return httpx.Response(
                303, headers={"set-cookie": "jwt=issued-cookie; Secure; Path=/gateway/test"}
            )
        assert "Authorization" not in req.headers
        assert req.headers["Cookie"] == "jwt=issued-cookie"
        if "/node/containerlogs/" in req.url.path:
            return httpx.Response(307, headers={"location": JOB})
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            stream=Stream([html_log("password=private-value\nissued-cookie\nEOF")]),
        )

    settings = log_settings(tmp_path).model_copy(update={"knox_sso_url": ROOT + "/sso"})
    adapter = SparkExecutorLogAdapter(
        settings=settings,
        secrets=SparkSecrets(
            username=SecretStr("synthetic-user"), password=SecretStr("private-value")
        ),
        event_logs=FakeGateway(),
        transport=httpx.MockTransport(handler),
    )
    route = _LogRoute(settings, request(log_type="stdout"), ORIGINAL)
    try:
        data = await adapter._receive(route, deadline=time.monotonic() + 2)
        assert "private-value" not in data.text and "issued-cookie" not in data.text
        assert data.text.endswith("EOF")
        assert [req.method for req in calls] == ["POST", "GET", "GET"]
    finally:
        await adapter.close()


@pytest.mark.parametrize(
    "executor,missing", [("driver", False), ("1", False), ("1", True), ("9", True)]
)
async def test_resolve_verified_last_registration_without_refresh(
    tmp_path: Path, executor: str, missing: bool
) -> None:
    import httpx

    from mcp_stdio.plugins.spark.cache import SparkEventLogAdapter
    from mcp_stdio.plugins.spark.config import SparkSecrets
    from mcp_stdio.plugins.spark.executor_logs import SparkExecutorLogAdapter
    from tests.unit.plugins.spark.fixtures import archive_bytes, encode, events
    from tests.unit.plugins.spark.test_http_client import Stream

    records = events("2")
    records[1]["Driver Logs"] = {"stdout": ORIGINAL}
    records.insert(
        2,
        {
            "Event": "SparkListenerExecutorAdded",
            "Executor ID": "1",
            "Executor Info": {"Log Urls": {"stdout": ORIGINAL.replace("000001", "000007")}},
        },
    )
    if executor == "1" and missing:
        records.insert(
            3,
            {
                "Event": "SparkListenerExecutorAdded",
                "Executor ID": "1",
                "Executor Info": {"Log Urls": {}},
            },
        )
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(
            200, stream=Stream([archive_bytes({"application_1_42_2": encode(records)})])
        )

    settings = log_settings(tmp_path)
    source = SparkEventLogAdapter(
        settings=settings, secrets=SparkSecrets(), transport=httpx.MockTransport(handler)
    )
    adapter = SparkExecutorLogAdapter(settings=settings, secrets=SparkSecrets(), event_logs=source)
    try:
        for _ in range(2):
            if missing:
                with pytest.raises(SparkGatewayError) as error:
                    await adapter._resolve(
                        request(executor_id=executor, log_type="stdout"),
                        deadline=time.monotonic() + 2,
                    )
                assert error.value.tool_error.category == ErrorCategory.NOT_FOUND
            else:
                route, file = await adapter._resolve(
                    request(executor_id=executor, log_type="stdout"), deadline=time.monotonic() + 2
                )
                assert route.container.endswith("000007" if executor == "1" else "000001")
                assert len(file.sha256) == 64
        assert len(calls) == 1
    finally:
        await adapter.close()
        await source.close()


@pytest.mark.parametrize(
    "mode,category,count",
    [
        ("foreign", "UNEXPECTED_RESPONSE", 1),
        ("login", "AUTHENTICATION_FAILED", 1),
        ("loop", "UNEXPECTED_RESPONSE", 2),
        ("excess", "UNEXPECTED_RESPONSE", 4),
        ("overflow", "UPSTREAM_ERROR", 1),
        ("redirect_overflow", "UPSTREAM_ERROR", 1),
        ("encoding", "UNEXPECTED_RESPONSE", 1),
        ("login200", "AUTHENTICATION_FAILED", 1),
        ("404", "NOT_FOUND", 1),
    ],
)
async def test_network_rejects_unsafe_or_oversized_responses(
    tmp_path: Path, mode: str, category: str, count: int
) -> None:
    import httpx

    from mcp_stdio.plugins.spark.config import SparkSecrets
    from mcp_stdio.plugins.spark.executor_logs import SparkExecutorLogAdapter, _LogRoute
    from tests.unit.plugins.spark.test_http_client import Stream

    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if mode == "foreign":
            return httpx.Response(
                307, headers={"location": JOB.replace("history.example", "foreign.example")}
            )
        if mode == "login":
            return httpx.Response(302, headers={"location": ROOT + "/login"})
        if mode in {"loop", "excess"}:
            location = (
                JOB
                if len(calls) == 1
                else re.sub(
                    r"node.nodes.example:[0-9]+/",
                    f"node.nodes.example:{8041 + len(calls)}/",
                    str(req.url),
                )
            )
            if mode == "loop" and len(calls) == 2:
                location = (
                    ORIGINAL.replace(
                        "http://node.nodes.example:8042/node", ROOT + "/yarn/nodemanager/node"
                    )
                    + "&scheme=http&host=node.nodes.example&port=8042"
                )
            return httpx.Response(307, headers={"location": location})
        if mode in {"overflow", "redirect_overflow"}:
            return httpx.Response(
                307 if mode.startswith("redirect") else 200,
                headers={"location": JOB},
                stream=Stream([b"x" * (8 * 1024 * 1024 + 1)]),
            )
        if mode == "encoding":
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=latin1"},
                stream=Stream([html_log()]),
            )
        if mode == "404":
            return httpx.Response(404)
        return httpx.Response(200, stream=Stream([b'<form><input type="password"></form>']))

    settings = log_settings(tmp_path)
    adapter = SparkExecutorLogAdapter(
        settings=settings,
        secrets=SparkSecrets(),
        event_logs=FakeGateway(),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(SparkGatewayError) as error:
            await adapter._receive(
                _LogRoute(settings, request(log_type="stdout"), ORIGINAL),
                deadline=time.monotonic() + 2,
            )
        assert error.value.tool_error.category.value == category
        assert len(calls) == count
    finally:
        await adapter.close()


def test_reused_redactor_removes_folded_headers_and_standalone_bearer() -> None:
    from mcp_stdio.plugins.spark.files import redact_event

    value: dict[str, object] = {
        "Event": "DiagnosticText",
        "text": (
            "Cookie: key=unknown-cookie\n  folded-cookie\n"
            "Authorization: Bearer unknown-header\n  folded-auth\n"
            "Bearer standalone-token\nEOF"
        ),
    }
    redacted = str(redact_event(value, ()))
    for secret in (
        "unknown-cookie",
        "folded-cookie",
        "unknown-header",
        "folded-auth",
        "standalone-token",
    ):
        assert secret not in redacted
    assert "EOF" in redacted


async def make_adapter(tmp_path: Path, text: str = "EOF", *, total: int | None = None):
    import httpx

    from mcp_stdio.plugins.spark.cache import SparkEventLogAdapter
    from mcp_stdio.plugins.spark.config import SparkSecrets
    from mcp_stdio.plugins.spark.executor_logs import SparkExecutorLogAdapter
    from tests.unit.plugins.spark.fixtures import archive_bytes, encode, events
    from tests.unit.plugins.spark.test_http_client import Stream

    records = events("2")
    records[1]["Driver Logs"] = {"stdout": ORIGINAL}

    def handler(req: httpx.Request) -> httpx.Response:
        if "/api/v1/" in req.url.path:
            return httpx.Response(
                200, stream=Stream([archive_bytes({"application_1_42_2": encode(records)})])
            )
        return httpx.Response(200, stream=Stream([html_log(text, length=total)]))

    settings = log_settings(tmp_path)
    source = SparkEventLogAdapter(
        settings=settings, secrets=SparkSecrets(), transport=httpx.MockTransport(handler)
    )
    return SparkExecutorLogAdapter(
        settings=settings,
        secrets=SparkSecrets(),
        event_logs=source,
        transport=httpx.MockTransport(handler),
    ), source


async def test_publish_private_fresh_evidence_and_manifest(tmp_path: Path) -> None:
    import hashlib
    import json
    import stat

    adapter, source = await make_adapter(tmp_path, "token=unconfigured-private\nEOF")
    try:
        first = await adapter.fetch(request(log_type="stdout"), deadline=time.monotonic() + 3)
        second = await adapter.fetch(request(log_type="stdout"), deadline=time.monotonic() + 3)
        assert first.local_path != second.local_path
        path, manifest = Path(first.local_path), Path(first.manifest_path)
        raw = path.read_bytes()
        assert raw.endswith(b"EOF") and b"unconfigured-private" not in raw
        assert first.size_bytes == len(raw) and first.sha256 == hashlib.sha256(raw).hexdigest()
        body = json.loads(manifest.read_text())
        assert body["event_log_sha256"] and Path(body["event_log_path"]).is_file()
        assert body["source_size_bytes"] == len(b"token=unconfigured-private\nEOF")
        assert body["source_kind"] == "node_manager" and body["format_version"] == 1
        assert body["coverage"] == "complete"
        for file in (path, manifest):
            assert stat.S_IMODE(file.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        assert not list((tmp_path / "l3").rglob(".part-*"))
    finally:
        await adapter.close()
        await source.close()


@pytest.mark.parametrize("component", ["executor-logs", "application_1_42", "attempt-2", "driver"])
async def test_publication_rejects_symlink_descendants(tmp_path: Path, component: str) -> None:
    adapter, source = await make_adapter(tmp_path)
    root = tmp_path / "l3"
    parts = ["executor-logs", "application_1_42", "attempt-2", "driver"]
    parent = root
    target = tmp_path / "outside"
    target.mkdir()
    for part in parts:
        if part == component:
            (parent / part).symlink_to(target, target_is_directory=True)
            break
        parent = parent / part
        parent.mkdir(mode=0o700)
    try:
        with pytest.raises(SparkGatewayError):
            await adapter.fetch(request(log_type="stdout"), deadline=time.monotonic() + 3)
        assert list(target.iterdir()) == []
    finally:
        await adapter.close()
        await source.close()


async def test_output_caps_eof_and_confirmed_start_fragment(tmp_path: Path) -> None:
    adapter, source = await make_adapter(tmp_path, "unsafe-fragment\ncomplete\nEOF", total=5000)
    try:
        result = await adapter.fetch(request(log_type="stdout"), deadline=time.monotonic() + 3)
        assert Path(result.local_path).read_text() == "complete\nEOF"
        assert result.coverage == "tail"
    finally:
        await adapter.close()
        await source.close()
    other = tmp_path / "other"
    other.mkdir()
    adapter, source = await make_adapter(other, "token=x\n" * 120000 + "EOF")
    try:
        result = await adapter.fetch(
            request(log_type="stdout", tail_bytes=1048576), deadline=time.monotonic() + 5
        )
        raw = Path(result.local_path).read_bytes()
        assert len(raw) <= 1048576 and raw.endswith(b"EOF")
        assert result.coverage == "tail"
    finally:
        await adapter.close()
        await source.close()


async def test_disabled_configuration_never_resolves_eventlog(tmp_path: Path) -> None:
    from mcp_stdio.plugins.spark.config import SparkSecrets, SparkSettings
    from mcp_stdio.plugins.spark.executor_logs import SparkExecutorLogAdapter

    source = FakeGateway()
    adapter = SparkExecutorLogAdapter(
        settings=SparkSettings(history_server_url=ROOT, cache_dir=str(tmp_path)),
        secrets=SparkSecrets(),
        event_logs=source,
    )
    try:
        with pytest.raises(SparkGatewayError) as error:
            await adapter.fetch(request(), deadline=time.monotonic() + 1)
        assert error.value.tool_error.category == ErrorCategory.CONFIG_ERROR
        assert source.calls == []
    finally:
        await adapter.close()


async def test_failed_publication_keeps_prior_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    adapter, source = await make_adapter(tmp_path)
    try:
        prior = await adapter.fetch(request(log_type="stdout"), deadline=time.monotonic() + 3)

        def fail(*args: object, **kwargs: object) -> None:
            raise OSError("untrusted private upstream detail")

        monkeypatch.setattr(os, "rename", fail)
        with pytest.raises(SparkGatewayError) as error:
            await adapter.fetch(request(log_type="stdout"), deadline=time.monotonic() + 3)
        assert error.value.tool_error.category == ErrorCategory.UPSTREAM_ERROR
        assert Path(prior.local_path).is_file()
        assert not list((tmp_path / "l3").rglob(".part-*"))
        assert "untrusted" not in str(error.value)
    finally:
        await adapter.close()
        await source.close()


async def test_login_cookie_rotation_keeps_all_redaction_values(tmp_path: Path) -> None:
    import httpx
    from pydantic import SecretStr

    from mcp_stdio.plugins.spark.config import SparkSecrets
    from mcp_stdio.plugins.spark.executor_logs import SparkExecutorLogAdapter, _LogRoute
    from tests.unit.plugins.spark.test_http_client import Stream

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(
                303, headers={"set-cookie": "jwt=first-issued-cookie; Path=/; Secure"}
            )
        return httpx.Response(
            200,
            headers={"set-cookie": "jwt=second-issued-cookie; Path=/; Secure"},
            stream=Stream([html_log("first-issued-cookie\nsecond-issued-cookie\nEOF")]),
        )

    settings = log_settings(tmp_path).model_copy(update={"knox_sso_url": ROOT + "/sso"})
    adapter = SparkExecutorLogAdapter(
        settings=settings,
        secrets=SparkSecrets(
            username=SecretStr("synthetic-user"), password=SecretStr("synthetic-password")
        ),
        event_logs=FakeGateway(),
        transport=httpx.MockTransport(handler),
    )
    try:
        content = await adapter._receive(
            _LogRoute(settings, request(log_type="stdout"), ORIGINAL), deadline=time.monotonic() + 2
        )
        assert (
            "first-issued-cookie" not in content.text and "second-issued-cookie" not in content.text
        )
    finally:
        await adapter.close()


@pytest.mark.parametrize(
    "original",
    [
        ORIGINAL.replace(":8042", ":bad"),
        ORIGINAL.split("?")[0] + "?start",
        ORIGINAL.replace("/owner/", "/%ff/"),
    ],
)
def test_malformed_url_has_safe_domain_error(tmp_path: Path, original: str) -> None:
    from mcp_stdio.plugins.spark.executor_logs import _LogRoute

    with pytest.raises(SparkGatewayError) as error:
        _LogRoute(log_settings(tmp_path), request(log_type="stdout"), original)
    assert error.value.tool_error.category == ErrorCategory.UNEXPECTED_RESPONSE


async def test_unsupported_redirect_is_unexpected(tmp_path: Path) -> None:
    import httpx

    from mcp_stdio.plugins.spark.config import SparkSecrets
    from mcp_stdio.plugins.spark.executor_logs import SparkExecutorLogAdapter, _LogRoute

    adapter = SparkExecutorLogAdapter(
        settings=log_settings(tmp_path),
        secrets=SparkSecrets(),
        event_logs=FakeGateway(),
        transport=httpx.MockTransport(lambda req: httpx.Response(301, headers={"location": JOB})),
    )
    try:
        with pytest.raises(SparkGatewayError) as error:
            await adapter._receive(
                _LogRoute(log_settings(tmp_path), request(log_type="stdout"), ORIGINAL),
                deadline=time.monotonic() + 1,
            )
        assert error.value.tool_error.category == ErrorCategory.UNEXPECTED_RESPONSE
    finally:
        await adapter.close()


async def test_shutdown_cancels_active_and_queued_calls_before_lock_release(tmp_path: Path) -> None:
    import httpx

    from mcp_stdio.plugins.spark.cache import SparkEventLogAdapter
    from mcp_stdio.plugins.spark.config import SparkSecrets
    from mcp_stdio.plugins.spark.executor_logs import SparkExecutorLogAdapter
    from tests.unit.plugins.spark.fixtures import archive_bytes, encode, events
    from tests.unit.plugins.spark.test_http_client import Stream

    entered, cancelled = asyncio.Event(), asyncio.Event()
    records = events("2")
    records[1]["Driver Logs"] = {"stdout": ORIGINAL}

    async def handler(req: httpx.Request) -> httpx.Response:
        if "/api/v1/" in req.url.path:
            return httpx.Response(
                200, stream=Stream([archive_bytes({"application_1_42_2": encode(records)})])
            )
        entered.set()
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()
        return httpx.Response(200)

    settings = log_settings(tmp_path)
    source = SparkEventLogAdapter(
        settings=settings, secrets=SparkSecrets(), transport=httpx.MockTransport(handler)
    )
    adapter = SparkExecutorLogAdapter(
        settings=settings,
        secrets=SparkSecrets(),
        event_logs=source,
        transport=httpx.MockTransport(handler),
    )
    task = asyncio.create_task(
        adapter.fetch(request(log_type="stdout"), deadline=time.monotonic() + 3)
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        with pytest.raises(SparkGatewayError) as error:
            await adapter.fetch(request(log_type="stdout"), deadline=time.monotonic() + 0.01)
        assert error.value.tool_error.category == ErrorCategory.TIMEOUT
        await adapter.close()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set() and not adapter._acquisitions
        assert source._lock_fd is not None
        assert not list((tmp_path / "l3").rglob(".part-*"))
        assert (
            await source.lookup("application_1_42", "2", deadline=time.monotonic() + 1) is not None
        )
    finally:
        await adapter.close()
        await source.close()
    replacement = SparkEventLogAdapter(settings=settings, secrets=SparkSecrets())
    await replacement.close()


@pytest.mark.parametrize(
    "text,secret",
    [
        (
            "Authorization: Bearer first-line\n unconfigured-folded-ticket\nEOF",
            "unconfigured-folded-ticket",
        ),
        ('password="first-line\nunknown-assignment-value"\nEOF', "unknown-assignment-value"),
    ],
)
async def test_small_tail_redacts_before_discarding_context(
    tmp_path: Path, text: str, secret: str
) -> None:
    adapter, source = await make_adapter(tmp_path, text, total=len(text.encode()) + 100)
    try:
        result = await adapter.fetch(
            request(log_type="stdout", tail_bytes=max(64, len(text.encode()))),
            deadline=time.monotonic() + 3,
        )
        saved = Path(result.local_path).read_text()
        assert secret not in saved and saved.endswith("EOF")
    finally:
        await adapter.close()
        await source.close()


async def test_failed_staging_open_removes_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    adapter, source = await make_adapter(tmp_path)
    open_real = os.open

    def fail_stage(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if str(path).startswith(".part-"):
            raise OSError("synthetic descriptor exhaustion")
        return open_real(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", fail_stage)
    try:
        with pytest.raises(SparkGatewayError):
            await adapter.fetch(request(log_type="stdout"), deadline=time.monotonic() + 3)
        assert not list((tmp_path / "l3").rglob(".part-*"))
    finally:
        await adapter.close()
        await source.close()


async def test_oversized_source_range_is_rejected_even_if_redaction_shrinks_it(
    tmp_path: Path,
) -> None:
    adapter, source = await make_adapter(tmp_path, "EARLY MARKER\npassword=" + "x" * 1000 + "\nEOF")
    try:
        with pytest.raises(SparkGatewayError) as error:
            await adapter.fetch(
                request(log_type="stdout", tail_bytes=64), deadline=time.monotonic() + 3
            )
        assert error.value.tool_error.category == ErrorCategory.UNEXPECTED_RESPONSE
        assert not list((tmp_path / "l3").rglob("stdout.log"))
    finally:
        await adapter.close()
        await source.close()
