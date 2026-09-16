"""Zeppelin HTTP adapter mock-transport tests."""

from __future__ import annotations

import asyncio
import gc
import json
import logging
from collections.abc import AsyncIterator
from urllib.parse import parse_qs

import httpx
import pytest

from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation
from mcp_stdio.plugins.zeppelin.config import ZeppelinSecrets, ZeppelinSettings
from mcp_stdio.plugins.zeppelin.gateway import ZeppelinGatewayError
from mcp_stdio.plugins.zeppelin.http_client import ZeppelinHttpClient
from mcp_stdio.plugins.zeppelin.models import (
    CancelParagraphResult,
    ParagraphStatus,
    RestartInterpreterResult,
)
from tests.unit.plugins.zeppelin.test_websocket_client import LifecycleSocket, binding, response


def _settings(**overrides: object) -> ZeppelinSettings:
    base: dict[str, object] = {"base_url": "https://zep.example/api"}
    base.update(overrides)
    return ZeppelinSettings.model_validate(base)


def _no_secrets() -> ZeppelinSecrets:
    return ZeppelinSecrets()


def _secrets() -> ZeppelinSecrets:
    return ZeppelinSecrets.model_validate(
        {"username": "u", "password": "p"}
    )


def _mock_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _adapter(
    transport: httpx.MockTransport,
    *,
    secrets: ZeppelinSecrets | None = None,
    settings: ZeppelinSettings | None = None,
) -> ZeppelinHttpClient:
    s = settings or _settings()
    sec = secrets or _no_secrets()
    return ZeppelinHttpClient(
        settings=s,
        secrets=sec,
        transport=transport,
    )


def _ok(body: object) -> httpx.Response:
    return httpx.Response(200, json={"status": "OK", "message": "", "body": body})


class DiscoveryTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.paths: list[str] = []
        self.pause = ""
        self.entered = {path: asyncio.Event() for path in (
            "/api/login", "/api/notebook/first", "/api/security/ticket",
        )}
        self.release = {path: asyncio.Event() for path in self.entered}
        self.tickets = 0
        self.closes = 0
        self.close_entered = asyncio.Event()
        self.close_release = asyncio.Event()
        self.pause_close = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.paths.append(path)
        if path in self.entered:
            self.entered[path].set()
        if self.pause == path:
            await self.release[path].wait()
        if path.endswith("/login"):
            return _ok(None)
        if path.endswith("/ticket"):
            self.tickets += 1
            return _ok({
                "principal": "fake-user", "ticket": f"ticket-{self.tickets}", "roles": "[]",
            })
        return _ok({"id": path.rsplit("/", 1)[-1]})

    async def aclose(self) -> None:
        self.closes += 1
        self.close_entered.set()
        if self.pause_close:
            await self.close_release.wait()


class DiscoverySockets:
    def __init__(self, *sockets: LifecycleSocket) -> None:
        self.sockets = list(sockets)
        self.calls = 0

    def __call__(self, url: str, **options: object) -> LifecycleSocket:
        socket = self.sockets[self.calls]
        self.calls += 1
        return socket(url, **options)


def discovery_adapter(
    transport: DiscoveryTransport, sockets: DiscoverySockets, timeout: float = 10,
) -> ZeppelinHttpClient:
    return ZeppelinHttpClient(
        settings=_settings(request_timeout_seconds=timeout), secrets=_secrets(),
        transport=transport, websocket_connector=sockets,
    )


async def test_discovery_serializes_http_tickets_and_socket_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()
    now = loop.time()
    monkeypatch.setattr(loop, "time", lambda: now)
    transport = DiscoveryTransport()
    first = LifecycleSocket(pause="receive")
    first.frames = [response([binding(id="first-setting")])]
    second = LifecycleSocket()
    second.frames = [response([binding(id="second-setting")])]
    sockets = DiscoverySockets(first, second)
    gateway = discovery_adapter(transport, sockets)
    active = asyncio.create_task(gateway.get_interpreter_bindings("first"))
    await first.entered["receive"].wait()
    waiter = asyncio.create_task(gateway.get_interpreter_bindings("second"))
    await asyncio.sleep(0)
    assert transport.paths == ["/api/login", "/api/notebook/first", "/api/security/ticket"]
    assert sockets.calls == 1
    now += 3
    first.release["receive"].set()
    assert (await active)[0].setting_id == "first-setting"
    assert (await waiter)[0].setting_id == "second-setting"
    assert [first.sent[0]["ticket"], second.sent[0]["ticket"]] == ["ticket-1", "ticket-2"]
    assert first.sent[0]["data"] == {"noteId": "first"}
    assert second.sent[0]["data"] == {"noteId": "second"}
    assert second.calls[0]["open_timeout"] == 7
    assert first.closes == second.closes == 1
    await gateway.close()


async def test_one_deadline_covers_login_notebook_ticket_connect_send_receive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()
    now = loop.time()
    monkeypatch.setattr(loop, "time", lambda: now)
    transport = DiscoveryTransport()
    transport.pause = "/api/login"
    socket = LifecycleSocket(pause="connect")
    gateway = discovery_adapter(transport, DiscoverySockets(socket))
    task = asyncio.create_task(gateway.get_interpreter_bindings("first"))
    for path, following in (
        ("/api/login", "/api/notebook/first"),
        ("/api/notebook/first", "/api/security/ticket"),
        ("/api/security/ticket", ""),
    ):
        await transport.entered[path].wait()
        now += 2
        transport.pause = following
        transport.release[path].set()
    for stage, following in (("connect", "send"), ("send", "receive")):
        await socket.entered[stage].wait()
        now += 1
        socket.pause = following
        socket.release[stage].set()
    await socket.entered["receive"].wait()
    now += 2.01
    with pytest.raises(ZeppelinGatewayError) as error:
        await task
    assert error.value.tool_error.category == ErrorCategory.TIMEOUT
    assert error.value.tool_error.retryable
    assert socket.calls[0]["open_timeout"] == 4
    assert socket.calls[0]["close_timeout"] == 5
    assert socket.closes == 1
    assert socket.running == set()
    await gateway.close()


async def test_cancelled_waiter_never_touches_active_query() -> None:
    transport = DiscoveryTransport()
    socket = LifecycleSocket(pause="receive")
    sockets = DiscoverySockets(socket)
    gateway = discovery_adapter(transport, sockets)
    active = asyncio.create_task(gateway.get_interpreter_bindings("first"))
    await socket.entered["receive"].wait()
    waiter = asyncio.create_task(gateway.get_interpreter_bindings("second"))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert not active.done()
    assert socket.running == {"receive"}
    socket.release["receive"].set()
    assert await active == ()
    assert sockets.calls == 1
    await gateway.close()


async def test_lock_wait_consumes_deadline_without_starting_upstream_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()
    now = loop.time()
    monkeypatch.setattr(loop, "time", lambda: now)
    transport = DiscoveryTransport()
    socket = LifecycleSocket(pause="receive")
    gateway = discovery_adapter(transport, DiscoverySockets(socket))
    active = asyncio.create_task(gateway.get_interpreter_bindings("first"))
    await socket.entered["receive"].wait()
    waiter = asyncio.create_task(gateway.get_interpreter_bindings("second"))
    await asyncio.sleep(0)
    now += 10.01
    for task in (waiter, active):
        with pytest.raises(ZeppelinGatewayError) as error:
            await task
        assert error.value.tool_error.category == ErrorCategory.TIMEOUT
    assert "/api/notebook/second" not in transport.paths
    assert socket.running == set()
    await gateway.close()


@pytest.mark.parametrize("stage", ["http", "connect", "send", "receive", "close", "complete"])
async def test_shutdown_cancels_active_and_waiting_discovery_and_rejects_new_work(
    stage: str,
) -> None:
    transport = DiscoveryTransport()
    if stage == "http":
        transport.pause = "/api/login"
    socket = LifecycleSocket(pause=stage)
    gateway = discovery_adapter(transport, DiscoverySockets(socket))
    active = asyncio.create_task(gateway.get_interpreter_bindings("first"))
    if stage == "http":
        await transport.entered["/api/login"].wait()
    elif stage == "complete":
        assert await active == ()
    else:
        await socket.entered[stage].wait()
    waiter = asyncio.create_task(gateway.get_interpreter_bindings("second"))
    close = asyncio.create_task(gateway.close())
    await asyncio.sleep(0)
    if stage == "close":
        socket.release["close"].set()
    await close
    if stage != "complete":
        with pytest.raises(asyncio.CancelledError):
            await active
    with pytest.raises(asyncio.CancelledError):
        await waiter
    with pytest.raises(asyncio.CancelledError):
        await gateway.get_interpreter_bindings("third")
    await gateway.close()
    assert transport.closes == 1
    assert socket.running == set()
    assert "/api/notebook/second" not in transport.paths


@pytest.mark.parametrize("stage", ["connect", "send", "receive"])
async def test_gateway_caller_cancellation_cleans_socket_and_allows_next_query(stage: str) -> None:
    transport = DiscoveryTransport()
    first = LifecycleSocket(pause=stage)
    second = LifecycleSocket()
    gateway = discovery_adapter(transport, DiscoverySockets(first, second))
    task = asyncio.create_task(gateway.get_interpreter_bindings("first"))
    await first.entered[stage].wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert first.running == set()
    assert await gateway.get_interpreter_bindings("second") == ()
    await gateway.close()


async def test_shutdown_uses_one_cleanup_allowance_for_socket_and_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()
    now = loop.time()
    monkeypatch.setattr(loop, "time", lambda: now)
    transport = DiscoveryTransport()
    transport.pause_close = True
    socket = LifecycleSocket(pause="close")
    gateway = discovery_adapter(transport, DiscoverySockets(socket))
    active = asyncio.create_task(gateway.get_interpreter_bindings("first"))
    await socket.entered["close"].wait()
    close = asyncio.create_task(gateway.close())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    now += 4
    socket.release["close"].set()
    await transport.close_entered.wait()
    now += 1.01
    for _ in range(30):
        await asyncio.sleep(0)
    try:
        assert close.done(), "socket and HTTP close reset the shutdown allowance"
    finally:
        transport.close_release.set()
        await asyncio.gather(active, close, return_exceptions=True)
    with pytest.raises(asyncio.CancelledError):
        await active
    assert transport.closes == 1


class BlockingCloseStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.reading = asyncio.Event()
        self.closing = asyncio.Event()
        self.release_close = asyncio.Event()
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.reading.set()
        await asyncio.Event().wait()
        yield b""

    async def aclose(self) -> None:
        self.closing.set()
        try:
            await self.release_close.wait()
        finally:
            self.closed = True


async def test_cancelling_http_read_bounds_response_stream_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()
    now = loop.time()
    monkeypatch.setattr(loop, "time", lambda: now)
    stream = BlockingCloseStream()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    gateway = ZeppelinHttpClient(
        settings=_settings(request_timeout_seconds=10), secrets=_no_secrets(),
        transport=httpx.MockTransport(handler),
        websocket_connector=DiscoverySockets(),
    )
    task = asyncio.create_task(gateway.get_interpreter_bindings("first"))
    await stream.reading.wait()
    task.cancel()
    await stream.closing.wait()
    now += 5.01
    for _ in range(30):
        await asyncio.sleep(0)
    try:
        assert task.done(), "HTTP response stream close outlived its cleanup allowance"
    finally:
        stream.release_close.set()
        await asyncio.gather(task, return_exceptions=True)
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.closed
    await gateway.close()


async def test_caller_cancellation_wins_race_with_completed_gateway_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = discovery_adapter(DiscoveryTransport(), DiscoverySockets())

    async def fail_and_cancel(
        notebook_id: str, deadline: float, cancelled: asyncio.Event,
    ) -> tuple[()]:
        caller.cancel()
        raise ZeppelinGatewayError(ToolError.create(
            category=ErrorCategory.CONNECTION_FAILED,
            operation=ToolOperation.GET_INTERPRETER_BINDINGS,
            retryable=True,
        ))

    monkeypatch.setattr(gateway, "_serialized_discovery", fail_and_cancel)
    caller = asyncio.create_task(gateway.get_interpreter_bindings("first"))
    with pytest.raises(asyncio.CancelledError):
        await caller
    await gateway.close()


async def test_shutdown_during_caller_cancellation_joins_http_stream_cleanup() -> None:
    stream = BlockingCloseStream()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    gateway = ZeppelinHttpClient(
        settings=_settings(), secrets=_no_secrets(), transport=httpx.MockTransport(handler),
        websocket_connector=DiscoverySockets(),
    )
    tasks_before = asyncio.all_tasks()
    caller = asyncio.create_task(gateway.get_interpreter_bindings("first"))
    await stream.reading.wait()
    caller.cancel()
    await stream.closing.wait()
    shutdown = asyncio.create_task(gateway.close())
    for _ in range(20):
        await asyncio.sleep(0)
    try:
        assert not shutdown.done(), "shutdown detached an in-progress HTTP cleanup"
    finally:
        stream.release_close.set()
        await asyncio.gather(caller, shutdown, return_exceptions=True)
    assert stream.closed
    assert asyncio.all_tasks() == tasks_before


async def test_waiter_cancellation_at_lock_handoff_starts_no_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = DiscoveryTransport()
    first = LifecycleSocket(pause="receive")
    sockets = DiscoverySockets(first, LifecycleSocket())
    gateway = discovery_adapter(transport, sockets)

    class HandoffLock(asyncio.Lock):
        def release(self) -> None:
            super().release()
            waiter.cancel()

    monkeypatch.setattr(gateway, "_discovery_lock", HandoffLock())
    active = asyncio.create_task(gateway.get_interpreter_bindings("first"))
    await first.entered["receive"].wait()
    waiter = asyncio.create_task(gateway.get_interpreter_bindings("second"))
    for _ in range(5):
        await asyncio.sleep(0)
    first.release["receive"].set()
    assert await active == ()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert "/api/notebook/second" not in transport.paths
    assert sockets.calls == 1
    await gateway.close()


async def test_http_client_close_has_hard_deadline_when_transport_rejects_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()
    now = loop.time()
    monkeypatch.setattr(loop, "time", lambda: now)
    failures: list[dict[str, object]] = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: failures.append(context))

    class StubbornCloseTransport(DiscoveryTransport):
        close_task: asyncio.Task[object] | None = None

        async def aclose(self) -> None:
            self.closes += 1
            self.close_task = asyncio.current_task()
            self.close_entered.set()
            while not self.close_release.is_set():
                try:
                    await self.close_release.wait()
                except asyncio.CancelledError:
                    continue
            raise OSError("late close failure")

    transport = StubbornCloseTransport()
    gateway = discovery_adapter(transport, DiscoverySockets(LifecycleSocket()))
    assert await gateway.get_interpreter_bindings("first") == ()
    first = asyncio.create_task(gateway.close())
    await transport.close_entered.wait()
    second = asyncio.create_task(gateway.close())
    await asyncio.sleep(0)
    now += 5.01
    for _ in range(30):
        await asyncio.sleep(0)
    try:
        assert first.done() and second.done(), "HTTP close waited past the global deadline"
        assert transport.close_task is not None and not transport.close_task.done()
    finally:
        transport.close_release.set()
        await asyncio.gather(first, second, return_exceptions=True)
        for _ in range(10):
            await asyncio.sleep(0)
        assert transport.close_task is not None and transport.close_task.done()
        # Remove the test's own reference so an unobserved late failure is reported.
        transport.close_task = None
        gc.collect()
        loop.set_exception_handler(previous_handler)
    assert failures == []
    assert transport.closes == 1


class EOFClosingStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.closing = asyncio.Event()
        self.release_close = asyncio.Event()
        self.closed = False
        self.aborts = 0
        self.close_calls = 0
        self.close_failure: Exception | None = None

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'{"status":"OK","body":{"id":"first"}}'

    async def aclose(self) -> None:
        self.close_calls += 1
        self.closing.set()
        await self.release_close.wait()
        if self.close_failure is not None:
            raise self.close_failure
        self.closed = True

    def get_extra_info(self, info: str) -> EOFClosingStream | None:
        return self if info == "socket" else None

    def shutdown(self, how: int) -> None:
        self.aborts += 1
        self.closed = True
        self.release_close.set()


@pytest.mark.parametrize("shutdown", [False, True])
async def test_eof_response_close_is_owned_after_httpx_marks_response_closed(
    shutdown: bool,
) -> None:
    stream = EOFClosingStream()
    response = httpx.Response(200, stream=stream, extensions={"network_stream": stream})

    def handler(request: httpx.Request) -> httpx.Response:
        return response

    gateway = ZeppelinHttpClient(
        settings=_settings(), secrets=_no_secrets(), transport=httpx.MockTransport(handler),
        websocket_connector=DiscoverySockets(),
    )
    before = asyncio.all_tasks()
    caller = asyncio.create_task(gateway.get_interpreter_bindings("first"))
    await stream.closing.wait()
    assert response.is_closed and not stream.closed
    if shutdown:
        closer = asyncio.create_task(gateway.close())
    else:
        caller.cancel()
        closer = caller
    for _ in range(20):
        await asyncio.sleep(0)
    try:
        assert not closer.done(), "HTTPX's closed flag detached the actual stream closure"
    finally:
        stream.release_close.set()
        await asyncio.gather(caller, closer, return_exceptions=True)
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert stream.closed
    assert stream.close_calls == 1
    await gateway.close()
    assert asyncio.all_tasks() == before


async def test_eof_stream_close_is_force_released_at_cleanup_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()
    now = loop.time()
    monkeypatch.setattr(loop, "time", lambda: now)
    stream = EOFClosingStream()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream, extensions={"network_stream": stream})

    gateway = ZeppelinHttpClient(
        settings=_settings(), secrets=_no_secrets(), transport=httpx.MockTransport(handler),
        websocket_connector=DiscoverySockets(),
    )
    caller = asyncio.create_task(gateway.get_interpreter_bindings("first"))
    await stream.closing.wait()
    caller.cancel()
    await asyncio.sleep(0)
    now += 5.01
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert stream.aborts == 1
    assert stream.closed
    assert stream.close_calls == 1
    await gateway.close()


async def test_response_close_failure_aborts_stream_without_replacing_primary_error() -> None:
    stream = EOFClosingStream()
    stream.close_failure = OSError("close failed")
    stream.release_close.set()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, stream=stream, extensions={"network_stream": stream})

    gateway = ZeppelinHttpClient(
        settings=_settings(), secrets=_no_secrets(), transport=httpx.MockTransport(handler),
        websocket_connector=DiscoverySockets(),
    )
    with pytest.raises(ZeppelinGatewayError) as error:
        await gateway.get_interpreter_bindings("first")
    assert error.value.tool_error.category == ErrorCategory.PERMISSION_DENIED
    assert stream.closed and stream.aborts == 1
    assert stream.close_calls == 1
    await gateway.close()


async def test_create_notebook_returns_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/notebook"
        assert request.method == "POST"
        return _ok("2ABC123")

    adapter = _adapter(_mock_transport(handler))
    nb_id = await adapter.create_notebook("my-note")
    assert nb_id == "2ABC123"
    await adapter.close()


async def test_add_paragraph_encodes_opaque_notebook_id_in_path() -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        raw = request.url.raw_path
        seen_paths.append(raw.decode() if isinstance(raw, bytes) else raw)
        return _ok("paragraph_123")

    adapter = _adapter(_mock_transport(handler))
    pid = await adapter.add_paragraph("note/1", "title", "%spark\nbody")
    assert pid == "paragraph_123"
    assert seen_paths[-1] == "/api/notebook/note%2F1/paragraph"
    await adapter.close()


async def test_add_paragraph_sends_body_verbatim_without_injecting_shebang() -> None:
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        seen_payloads.append(_json.loads(request.content))
        return _ok("paragraph_456")

    adapter = _adapter(_mock_transport(handler))
    body = "%spark.sql\nSELECT 1"
    pid = await adapter.add_paragraph("note-1", "title", body)
    assert pid == "paragraph_456"
    assert seen_payloads[-1] == {"title": "title", "text": body}
    await adapter.close()


async def test_run_paragraph_uses_job_endpoint() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(200, json={"status": "OK"})

    adapter = _adapter(_mock_transport(handler))
    status = await adapter.run_paragraph("nb1", "p1")
    assert status == ParagraphStatus.PENDING
    assert seen[-1] == ("POST", "/api/notebook/job/nb1/p1")
    await adapter.close()


async def test_get_paragraph_status_normalizes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _ok({"status": "RUNNING"})

    adapter = _adapter(_mock_transport(handler))
    status = await adapter.get_paragraph_status("nb1", "p1")
    assert status is ParagraphStatus.RUNNING
    await adapter.close()


async def test_get_paragraph_result_parses_and_truncates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _ok(
            {
                "status": "FINISHED",
                "results": {
                    "code": "SUCCESS",
                    "msg": [{"type": "TEXT", "data": "hello\n"}],
                },
            }
        )

    adapter = _adapter(_mock_transport(handler), settings=_settings(max_result_bytes=3))
    status, outputs, error, truncated = await adapter.get_paragraph_result("nb1", "p1")
    assert status is ParagraphStatus.FINISHED
    assert len(outputs) == 1
    assert truncated is True
    assert error is None
    await adapter.close()


async def test_get_paragraph_result_error_state_preserves_outputs_and_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _ok(
            {
                "status": "ERROR",
                "results": {
                    "code": "ERROR",
                    "msg": [{"type": "TEXT", "data": "Traceback: boom"}],
                    "exception": "upstream exception",
                },
            }
        )

    adapter = _adapter(_mock_transport(handler))
    status, outputs, error, truncated = await adapter.get_paragraph_result("nb1", "p1")
    assert status is ParagraphStatus.ERROR
    assert len(outputs) == 1
    assert "Traceback: boom" in outputs[0].text
    assert error is not None
    assert "upstream exception" in error.message
    await adapter.close()


async def test_get_paragraph_result_error_ignores_empty_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _ok(
            {
                "status": "ERROR",
                "results": {
                    "code": "ERROR",
                    "msg": [{"type": "TEXT", "data": "ExitValue: 1"}],
                    "exception": "",
                },
            }
        )

    adapter = _adapter(_mock_transport(handler))
    status, outputs, error, truncated = await adapter.get_paragraph_result("nb1", "p1")
    assert status is ParagraphStatus.ERROR
    assert len(outputs) == 1
    assert outputs[0].text == "ExitValue: 1"
    assert error is None
    await adapter.close()


async def test_authentication_failure_maps_to_category() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"status": "FORBIDDEN"})

    adapter = _adapter(_mock_transport(handler), secrets=_secrets())
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await adapter.create_notebook("x")
    assert exc_info.value.tool_error.category == ErrorCategory.AUTHENTICATION_FAILED
    await adapter.close()


async def test_timeout_maps_to_category() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    adapter = _adapter(_mock_transport(handler))
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await adapter.create_notebook("x")
    assert exc_info.value.tool_error.category == ErrorCategory.TIMEOUT
    await adapter.close()


async def test_connection_failure_maps_to_category() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    adapter = _adapter(_mock_transport(handler))
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await adapter.create_notebook("x")
    assert exc_info.value.tool_error.category == ErrorCategory.CONNECTION_FAILED
    await adapter.close()


async def test_unexpected_response_shape_maps_to_category() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    adapter = _adapter(_mock_transport(handler))
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await adapter.create_notebook("x")
    assert exc_info.value.tool_error.category == ErrorCategory.UNEXPECTED_RESPONSE
    await adapter.close()


async def test_login_is_called_once_with_credentials() -> None:
    login_calls: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/login":
            login_calls.append({"path": request.url.path})
            return httpx.Response(
                200,
                json={"status": "OK", "body": {"principal": "u", "ticket": "t"}},
                headers={"set-cookie": "JSESSIONID=abc; Path=/"},
            )
        return _ok("nb1")

    adapter = _adapter(_mock_transport(handler), secrets=_secrets())
    await adapter.create_notebook("x")
    await adapter.create_notebook("y")
    assert len(login_calls) == 1
    await adapter.close()


async def test_close_is_idempotent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _ok("nb1")

    adapter = _adapter(_mock_transport(handler))
    await adapter.close()
    await adapter.close()


async def test_list_notebooks_builds_directory_tree() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/notebook"
        assert request.method == "GET"
        return _ok(
            [
                {"id": "nb-1", "path": "/team/note-a"},
                {"id": "nb-2", "path": "/team/note-b"},
                {"id": "nb-3", "path": "/solo"},
            ]
        )

    adapter = _adapter(_mock_transport(handler))
    tree = await adapter.list_notebooks()
    assert len(tree) == 2
    team = next(n for n in tree if n.name == "team")
    assert team.notebook_id is None
    assert len(team.children) == 2
    solo = next(n for n in tree if n.name == "solo")
    assert solo.notebook_id == "nb-3"
    await adapter.close()


async def test_restart_interpreter_calls_put_restart_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/login":
            return httpx.Response(200)
        assert request.url.path == "/api/interpreter/setting/restart/spark"
        assert request.method == "PUT"
        return _ok({
            "id": "spark",
            "name": "spark",
            "group": "spark",
            "status": "READY",
            "properties": {"key": "value"},
            "dependencies": ["jar1"],
            "option": {"remote": True},
            "interpreterGroup": [{"name": "spark", "class": "SparkInterpreter"}],
        })

    adapter = _adapter(_mock_transport(handler), secrets=_secrets())
    result = await adapter.restart_interpreter("spark")
    assert isinstance(result, RestartInterpreterResult)
    assert result.setting_id == "spark"
    assert result.name == "spark"
    assert result.group == "spark"
    assert result.status == "READY"
    await adapter.close()


async def test_restart_interpreter_discards_extra_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/login":
            return httpx.Response(200)
        return _ok({
            "id": "sh",
            "name": "sh",
            "group": "sh",
            "status": "READY",
            "properties": {"secret": "value"},
            "dependencies": ["evil.jar"],
        })

    adapter = _adapter(_mock_transport(handler), secrets=_secrets())
    result = await adapter.restart_interpreter("sh")
    assert result.setting_id == "sh"
    # Ensure model has only the 4 approved fields
    assert set(type(result).model_fields) == {"setting_id", "name", "group", "status"}
    await adapter.close()


async def test_restart_interpreter_maps_500_to_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/login":
            return httpx.Response(200)
        return httpx.Response(500, json={
            "exception": "NullPointerException",
            "stacktrace": "java.lang.NullPointerException",
        })

    adapter = _adapter(_mock_transport(handler), secrets=_secrets())
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await adapter.restart_interpreter("nonexistent")
    assert exc_info.value.tool_error.category == ErrorCategory.UPSTREAM_ERROR
    assert exc_info.value.tool_error.identifiers == {"setting_id": "nonexistent"}
    await adapter.close()


async def test_restart_interpreter_encodes_setting_id_in_path() -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/login":
            return httpx.Response(200)
        raw = request.url.raw_path
        seen_paths.append(raw.decode() if isinstance(raw, bytes) else raw)
        return _ok({"id": "spark", "name": "spark", "group": "spark", "status": "READY"})

    adapter = _adapter(_mock_transport(handler), secrets=_secrets())
    await adapter.restart_interpreter("spark")
    assert seen_paths[-1] == "/api/interpreter/setting/restart/spark"
    await adapter.close()


async def test_restart_interpreter_handles_unexpected_response_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/login":
            return httpx.Response(200)
        return _ok("not-a-dict")

    adapter = _adapter(_mock_transport(handler), secrets=_secrets())
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await adapter.restart_interpreter("spark")
    assert exc_info.value.tool_error.category == ErrorCategory.UNEXPECTED_RESPONSE
    await adapter.close()


async def test_cancel_paragraph_calls_delete_job_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/login":
            return httpx.Response(200)
        assert request.url.path == "/api/notebook/job/nb-1/p-1"
        assert request.method == "DELETE"
        return _ok(None)

    adapter = _adapter(_mock_transport(handler), secrets=_secrets())
    result = await adapter.cancel_paragraph("nb-1", "p-1")
    assert isinstance(result, CancelParagraphResult)
    assert result.notebook_id == "nb-1"
    assert result.paragraph_id == "p-1"
    await adapter.close()


async def test_cancel_paragraph_maps_500_to_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/login":
            return httpx.Response(200)
        return httpx.Response(500, json={"exception": "error"})

    adapter = _adapter(_mock_transport(handler), secrets=_secrets())
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await adapter.cancel_paragraph("nb-1", "p-1")
    assert exc_info.value.tool_error.category == ErrorCategory.UPSTREAM_ERROR
    await adapter.close()


async def test_cancel_paragraph_encodes_opaque_ids_in_path() -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/login":
            return httpx.Response(200)
        raw = request.url.raw_path
        seen_paths.append(raw.decode() if isinstance(raw, bytes) else raw)
        return _ok(None)

    adapter = _adapter(_mock_transport(handler), secrets=_secrets())
    await adapter.cancel_paragraph("note/1", "para/1")
    assert seen_paths[-1] == "/api/notebook/job/note%2F1/para%2F1"
    await adapter.close()


class _TrackedStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes], failure: Exception | None = None) -> None:
        self.chunks = chunks
        self.failure = failure
        self.closed = False
        self.read_count = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            self.read_count += 1
            yield chunk
        if self.failure is not None:
            raise self.failure

    async def aclose(self) -> None:
        self.closed = True


def _ticket(**overrides: object) -> dict[str, object]:
    return {"principal": "synthetic-user", "ticket": "synthetic-ticket", "roles": "[]",
            **overrides}


@pytest.mark.parametrize(
    ("base_url", "websocket_url", "origin", "api_prefix"),
    [
        ("http://zep.example/api", "ws://zep.example/ws", "http://zep.example", "/api"),
        (
            "https://zep.example:9443/proxy/api",
            "wss://zep.example:9443/proxy/ws",
            "https://zep.example:9443",
            "/proxy/api",
        ),
    ],
)
async def test_discovery_derives_strict_same_origin_websocket_target(
    base_url: str,
    websocket_url: str,
    origin: str,
    api_prefix: str,
) -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == f"{api_prefix}/notebook/note":
            return _ok({"id": "note"})
        assert request.url.path == f"{api_prefix}/security/ticket"
        return _ok(_ticket())

    adapter = _adapter(_mock_transport(handler), settings=_settings(base_url=base_url))
    context = await adapter._prepare_discovery(
        "note",
        operation=ToolOperation.GET_INTERPRETER_BINDINGS,
        identifiers={"notebook_id": "note"},
    )

    assert context.websocket_url == websocket_url
    assert context.origin == origin
    assert context.cookie_header is None
    assert paths == [f"{api_prefix}/notebook/note", f"{api_prefix}/security/ticket"]
    await adapter.close()


@pytest.mark.parametrize(
    "base_url",
    [
        "https://zep.example",
        "https://zep.example/",
        "https://zep.example/api-v2",
        "https://zep.example/myapi",
        "https://zep.example/proxy/custom",
        "https://zep.example/api/v2",
        "https://zep.example/proxy/%61pi",
        "http://:9443/api",
        "https://:443/api",
        "http://zep.example:not-a-port/api",
        "https://zep.example:not-a-port/api",
    ],
)
@pytest.mark.parametrize(
    "operation", [ToolOperation.GET_INTERPRETER_BINDINGS, ToolOperation.RESTART_INTERPRETER]
)
async def test_discovery_rejects_ambiguous_websocket_mount_before_network(
    base_url: str,
    operation: ToolOperation,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _ok({"id": "note"})

    adapter = _adapter(_mock_transport(handler), settings=_settings(base_url=base_url))
    with pytest.raises(ZeppelinGatewayError) as error:
        await adapter._prepare_discovery(
            "note",
            operation=operation,
            identifiers={
                "notebook_id": "note",
                "setting_id": "x" * 257,
                "password": "never-public",
            },
        )

    assert error.value.tool_error.category == ErrorCategory.CONFIG_ERROR
    assert error.value.tool_error.operation == operation
    assert error.value.tool_error.identifiers == {"notebook_id": "note"}
    assert error.value.tool_error.retryable is False
    assert calls == 0
    assert adapter._client is None
    await adapter.close()


@pytest.mark.parametrize(("scheme", "secure_cookie_expected"), [("http", False), ("https", True)])
async def test_discovery_copies_only_httpx_scoped_cookie_for_http_ws_target(
    scheme: str,
    secure_cookie_expected: bool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base_url = f"{scheme}://zep.example:9443/proxy/api"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/proxy/api/login":
            return httpx.Response(
                200,
                headers=[
                    ("set-cookie", "host_only=host-secret; Path=/proxy"),
                    ("set-cookie", "domain_cookie=domain-secret; Domain=zep.example; Path=/proxy"),
                    ("set-cookie", "ws_path=path-secret; Path=/proxy/ws"),
                    ("set-cookie", "api_path=api-secret; Path=/proxy/api"),
                    ("set-cookie", "secure_cookie=secure-secret; Path=/proxy; Secure"),
                    ("set-cookie", "expired_cookie=expired-secret; Path=/proxy; Max-Age=0"),
                ],
            )
        if request.url.path == "/proxy/api/notebook/note":
            return _ok({"id": "note"})
        assert request.url.path == "/proxy/api/security/ticket"
        return _ok(_ticket(ticket="ticket-secret", roles='["private-role"]'))

    adapter = _adapter(
        _mock_transport(handler),
        secrets=ZeppelinSecrets.model_validate(
            {"username": "username-secret", "password": "password-secret"}
        ),
        settings=_settings(base_url=base_url),
    )
    client = await adapter._ensure_client()
    client.cookies.set(
        "other_domain", "other-secret", domain="other.example", path="/proxy"
    )

    context = await adapter._prepare_discovery(
        "note",
        operation=ToolOperation.GET_INTERPRETER_BINDINGS,
        identifiers={"notebook_id": "note"},
    )
    http_ws_url = f"{scheme}://zep.example:9443/proxy/ws"
    expected_cookie = client.build_request("GET", http_ws_url).headers.get("cookie")
    assert context.cookie_header == expected_cookie
    assert context.websocket_url == f"{'wss' if scheme == 'https' else 'ws'}://zep.example:9443/proxy/ws"
    assert context.origin == f"{scheme}://zep.example:9443"
    assert context.cookie_header is not None
    cookie_names = {item.partition("=")[0].strip() for item in context.cookie_header.split(";")}
    assert {"host_only", "domain_cookie", "ws_path"} <= cookie_names
    assert ("secure_cookie" in cookie_names) is secure_cookie_expected
    assert cookie_names.isdisjoint(
        {"api_path", "expired_cookie", "other_domain"}
    )
    captured = capsys.readouterr()
    for secret in (
        "username-secret",
        "password-secret",
        "ticket-secret",
        "private-role",
        "host-secret",
        "domain-secret",
        "path-secret",
    ):
        assert secret not in repr(context)
        assert secret not in captured.out
        assert secret not in captured.err
        assert secret not in context.websocket_url
        assert secret not in context.origin
    await adapter.close()


async def test_discovery_rejects_redirect_without_forwarding_authentication(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.DEBUG)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/login":
            return httpx.Response(
                200, headers={"set-cookie": "JSESSIONID=cookie-secret; Path=/"}
            )
        return httpx.Response(
            302,
            headers={"location": "https://other.example/ws?ticket=redirect-secret"},
        )

    adapter = _adapter(
        _mock_transport(handler),
        secrets=ZeppelinSecrets.model_validate(
            {"username": "username-secret", "password": "password-secret"}
        ),
    )
    with pytest.raises(ZeppelinGatewayError) as error:
        await adapter._prepare_discovery(
            "note",
            operation=ToolOperation.GET_INTERPRETER_BINDINGS,
            identifiers={"notebook_id": "note"},
        )

    assert error.value.tool_error.category == ErrorCategory.UPSTREAM_ERROR
    assert [request.url.host for request in requests] == ["zep.example", "zep.example"]
    assert all(request.url.query == b"" for request in requests)
    assert all(request.url.userinfo == b"" for request in requests)
    assert adapter._client is not None
    assert adapter._client.follow_redirects is False
    assert adapter._client._trust_env is False
    captured = capsys.readouterr()
    for secret in (
        "username-secret",
        "password-secret",
        "cookie-secret",
        "redirect-secret",
    ):
        assert secret not in str(error.value)
        assert secret not in repr(error.value.tool_error)
        assert secret not in caplog.text
        assert secret not in captured.out
        assert secret not in captured.err
        assert all(secret not in str(request.url) for request in requests)
    await adapter.close()


async def test_discovery_prepares_fresh_tickets_with_one_lazy_authenticated_session(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    username, password = "synthetic+user&=中文", "synthetic+pass&= word"
    notebook_id = "note/1?#%"
    paths: list[bytes] = []
    streams: list[_TrackedStream] = []
    ticket_number = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal ticket_number
        paths.append(request.url.raw_path)
        assert request.url.host == "zep.example"
        if request.url.path == "/api/login":
            assert request.method == "POST"
            assert request.headers["content-type"] == "application/x-www-form-urlencoded"
            assert parse_qs(request.content.decode()) == {
                "userName": [username], "password": [password],
            }
            document = {"unused": "login content"}
            headers = {"set-cookie": "JSESSIONID=synthetic-session; Path=/api"}
        else:
            assert request.method == "GET"
            assert request.headers["cookie"] == "JSESSIONID=synthetic-session"
            headers = {}
            if request.url.path == "/api/security/ticket":
                ticket_number += 1
                body = _ticket(ticket=f"synthetic-ticket-{ticket_number}", roles='["reader"]')
            else:
                assert request.url.raw_path == b"/api/notebook/note%2F1%3F%23%25"
                body = {"id": notebook_id, "paragraphs": [{"text": "private-notebook-text"}]}
            document = {"status": "OK", "body": body}
        stream = _TrackedStream([json.dumps(document).encode()])
        streams.append(stream)
        return httpx.Response(200, stream=stream, headers=headers)

    adapter = _adapter(_mock_transport(handler), secrets=ZeppelinSecrets.model_validate(
        {"username": username, "password": password},
    ))
    assert adapter._client is None
    contexts = []
    for _ in range(2):
        context = await adapter._prepare_discovery(
            notebook_id, operation=ToolOperation.GET_INTERPRETER_BINDINGS,
            identifiers={"notebook_id": notebook_id},
        )
        contexts.append(context)
        assert context.principal == "synthetic-user"
        assert context.roles == '["reader"]'
        assert not hasattr(context, "paragraphs")
        assert not hasattr(context, "notebook")
    assert contexts[0].ticket == "synthetic-ticket-1"
    assert contexts[1].ticket == "synthetic-ticket-2"
    assert paths == [b"/api/login", b"/api/notebook/note%2F1%3F%23%25",
                     b"/api/security/ticket", b"/api/notebook/note%2F1%3F%23%25",
                     b"/api/security/ticket"]
    assert all(stream.closed for stream in streams)
    for secret in (username, password, "synthetic-ticket", "reader", "private-notebook-text"):
        assert secret not in repr(contexts)
        assert secret not in caplog.text
    await adapter.close()


@pytest.mark.parametrize("body", [None, [], "note", {}, {"id": 1}, {"id": "other"}])
async def test_discovery_rejects_notebook_body_without_exact_id(body: object) -> None:
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return _ok(body)

    adapter = _adapter(_mock_transport(handler))
    with pytest.raises(ZeppelinGatewayError) as error:
        await adapter._prepare_discovery(
            "note", operation=ToolOperation.GET_INTERPRETER_BINDINGS,
            identifiers={"notebook_id": "note"},
        )
    assert error.value.tool_error.category == ErrorCategory.UNEXPECTED_RESPONSE
    assert paths == ["/api/notebook/note"]
    await adapter.close()


@pytest.mark.parametrize("stage", ["login", "notebook/note", "security/ticket"])
@pytest.mark.parametrize("operation", [ToolOperation.GET_INTERPRETER_BINDINGS,
                                        ToolOperation.RESTART_INTERPRETER])
@pytest.mark.parametrize(("status", "category"), [
    (401, ErrorCategory.AUTHENTICATION_FAILED), (403, ErrorCategory.PERMISSION_DENIED),
    (404, ErrorCategory.NOT_FOUND), (500, ErrorCategory.UPSTREAM_ERROR),
    (302, ErrorCategory.UPSTREAM_ERROR),
])
async def test_discovery_http_errors_keep_safe_initiating_context(
    stage: str, operation: ToolOperation, status: int, category: ErrorCategory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    paths = []
    failed_stream = _TrackedStream([b"private-notebook-text synthetic-ticket secret-roles"])

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == f"/api/{stage}":
            return httpx.Response(status, stream=failed_stream,
                                  headers={"location": "https://other.example/"})
        if request.url.path == "/api/login":
            return httpx.Response(200)
        return _ok({"id": "note"})

    adapter = _adapter(_mock_transport(handler), secrets=_secrets())
    with pytest.raises(ZeppelinGatewayError) as error:
        await adapter._prepare_discovery(
            "note", operation=operation,
            identifiers={"notebook_id": "note", "setting_id": "x" * 257,
                         "password": "synthetic-password"},
        )
    expected = (ErrorCategory.UPSTREAM_ERROR
                if status == 404 and stage != "notebook/note" else category)
    assert error.value.tool_error.category == expected
    assert error.value.tool_error.operation == operation
    assert error.value.tool_error.identifiers == {"notebook_id": "note"}
    assert error.value.tool_error.retryable is False
    assert paths[-1] == f"/api/{stage}"
    assert failed_stream.closed
    for secret in ("private-notebook-text", "synthetic-ticket", "secret-roles",
                   "synthetic-password"):
        assert secret not in str(error.value)
        assert secret not in repr(error.value.tool_error)
        assert secret not in caplog.text
    await adapter.close()


@pytest.mark.parametrize("roles", [None, [], {}, 1, True, "", "broken", "null", '"reader"',
                                    "1", "true", "{}", "[[]]", "[{}]", "[1]", "[true]", "[null]"])
async def test_discovery_rejects_invalid_ticket_roles(roles: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _ok({"id": "note"} if request.url.path.endswith("/note") else _ticket(roles=roles))

    adapter = _adapter(_mock_transport(handler))
    with pytest.raises(ZeppelinGatewayError) as error:
        await adapter._prepare_discovery("note", operation=ToolOperation.GET_INTERPRETER_BINDINGS,
                                         identifiers={"notebook_id": "note"})
    assert error.value.tool_error.category == ErrorCategory.UNEXPECTED_RESPONSE
    await adapter.close()


@pytest.mark.parametrize("body", [None, [], {}, {"principal": "user", "ticket": "value"},
    _ticket(principal=""), _ticket(principal=1), _ticket(ticket=""), _ticket(ticket=False),
    _ticket(principal="\ud800"), _ticket(ticket="\udfff"),
    _ticket(principal="x" * 513), _ticket(ticket="x" * 513), _ticket(roles=" " * 513)])
async def test_discovery_rejects_missing_or_invalid_ticket_fields(body: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        response_body = {"id": "note"} if request.url.path.endswith("/note") else body
        return httpx.Response(200, content=json.dumps({"status": "OK", "body": response_body}))

    adapter = _adapter(_mock_transport(handler), settings=_settings(max_response_bytes=512))
    with pytest.raises(ZeppelinGatewayError) as error:
        await adapter._prepare_discovery("note", operation=ToolOperation.GET_INTERPRETER_BINDINGS,
                                         identifiers={"notebook_id": "note"})
    assert error.value.tool_error.category == ErrorCategory.UNEXPECTED_RESPONSE
    await adapter.close()


@pytest.mark.parametrize("allow_anonymous", [True, False])
async def test_discovery_anonymous_mode_requires_upstream_ticket(allow_anonymous: bool) -> None:
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/notebook/note":
            return _ok({"id": "note"})
        assert request.url.path == "/api/security/ticket"
        return _ok(_ticket(principal="anonymous")) if allow_anonymous else httpx.Response(401)

    adapter = _adapter(_mock_transport(handler))
    if allow_anonymous:
        context = await adapter._prepare_discovery(
            "note", operation=ToolOperation.GET_INTERPRETER_BINDINGS,
            identifiers={"notebook_id": "note"})
        assert context.principal == "anonymous"
    else:
        with pytest.raises(ZeppelinGatewayError) as error:
            await adapter._prepare_discovery(
                "note", operation=ToolOperation.GET_INTERPRETER_BINDINGS,
                identifiers={"notebook_id": "note"})
        assert error.value.tool_error.category == ErrorCategory.AUTHENTICATION_FAILED
    assert paths == ["/api/notebook/note", "/api/security/ticket"]
    await adapter.close()


@pytest.mark.parametrize("stage", ["login", "notebook/note", "security/ticket"])
@pytest.mark.parametrize("headers", [{}, {"content-length": "1"}, {"content-length": "10000"}])
async def test_discovery_caps_streamed_bodies_without_trusting_content_length(
    stage: str, headers: dict[str, str],
) -> None:
    stream = _TrackedStream([b"x" * 80, b"y" * 80, b"must-not-read"])
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == f"/api/{stage}":
            return httpx.Response(200, stream=stream, headers=headers)
        return _ok({"id": "note"})

    adapter = _adapter(_mock_transport(handler), settings=_settings(max_response_bytes=128),
                       secrets=_secrets())
    with pytest.raises(ZeppelinGatewayError) as error:
        await adapter._prepare_discovery("note", operation=ToolOperation.RESTART_INTERPRETER,
                                         identifiers={"notebook_id": "note", "setting_id": "spark"})
    assert error.value.tool_error.category == ErrorCategory.UNEXPECTED_RESPONSE
    assert error.value.tool_error.operation == ToolOperation.RESTART_INTERPRETER
    assert stream.read_count <= 2
    assert stream.closed
    assert paths[-1] == f"/api/{stage}"
    await adapter.close()


@pytest.mark.parametrize("document", [[], None, {"body": {"id": "note"}},
    {"status": "OK", "body": {"id": "other"}}, {"status": "ERROR", "body": {"id": "note"}}])
async def test_discovery_rejects_invalid_envelopes(document: object) -> None:
    adapter = _adapter(_mock_transport(lambda request: httpx.Response(200, json=document)))
    with pytest.raises(ZeppelinGatewayError) as error:
        await adapter._prepare_discovery("note", operation=ToolOperation.GET_INTERPRETER_BINDINGS,
                                         identifiers={"notebook_id": "note"})
    category = (ErrorCategory.UPSTREAM_ERROR if isinstance(document, dict)
                and document.get("status") == "ERROR" else ErrorCategory.UNEXPECTED_RESPONSE)
    assert error.value.tool_error.category == category
    await adapter.close()


@pytest.mark.parametrize("operation", [ToolOperation.GET_INTERPRETER_BINDINGS,
                                        ToolOperation.RESTART_INTERPRETER])
@pytest.mark.parametrize(("failure", "category"), [
    (httpx.ReadTimeout("synthetic-ticket"), ErrorCategory.TIMEOUT),
    (httpx.RemoteProtocolError("synthetic-ticket"), ErrorCategory.CONNECTION_FAILED),
])
async def test_discovery_stream_failures_close_and_preserve_context(
    operation: ToolOperation, failure: Exception, category: ErrorCategory,
) -> None:
    stream = _TrackedStream([b"{"], failure)
    adapter = _adapter(_mock_transport(lambda request: httpx.Response(200, stream=stream)))
    with pytest.raises(ZeppelinGatewayError) as error:
        await adapter._prepare_discovery("n" * 300, operation=operation,
                                         identifiers={"notebook_id": "n" * 300})
    assert stream.closed
    assert error.value.tool_error.operation == operation
    assert error.value.tool_error.category == category
    assert error.value.tool_error.identifiers == {}
    assert error.value.tool_error.retryable == (operation == ToolOperation.GET_INTERPRETER_BINDINGS)
    assert "synthetic-ticket" not in str(error.value)
    await adapter.close()


@pytest.mark.parametrize("operation", [ToolOperation.LIST_NOTEBOOKS,
                                        ToolOperation.RESTART_INTERPRETER])
async def test_legacy_login_errors_keep_the_initiating_operation(operation: ToolOperation) -> None:
    adapter = _adapter(_mock_transport(lambda request: httpx.Response(403)), secrets=_secrets())
    with pytest.raises(ZeppelinGatewayError) as error:
        if operation == ToolOperation.LIST_NOTEBOOKS:
            await adapter.list_notebooks()
        else:
            await adapter.restart_interpreter("spark")
    assert error.value.tool_error.operation == operation
    assert error.value.tool_error.category == ErrorCategory.AUTHENTICATION_FAILED
    await adapter.close()
