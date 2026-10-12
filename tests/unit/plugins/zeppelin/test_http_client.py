"""Zeppelin HTTP adapter mock-transport tests."""

from __future__ import annotations

import asyncio
import gc
import json
import logging
import socket
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Protocol, cast
from urllib.parse import parse_qs, quote

import httpx
import pytest

from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation
from mcp_stdio.plugins.zeppelin import http_client as adapter_module
from mcp_stdio.plugins.zeppelin.config import ZeppelinSecrets, ZeppelinSettings
from mcp_stdio.plugins.zeppelin.gateway import ZeppelinGatewayError
from mcp_stdio.plugins.zeppelin.http_client import (
    ZeppelinHttpClient,
    _TicketContext,  # pyright: ignore[reportPrivateUsage] - inspect ticket lifetime
)
from mcp_stdio.plugins.zeppelin.http_resources import HttpResources
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
        {"username": "configured-user-sentinel", "password": "configured-pass-sentinel"}
    )


def _mock_transport(
    handler: Callable[[httpx.Request], httpx.Response]
    | Callable[[httpx.Request], Coroutine[None, None, httpx.Response]],
) -> httpx.MockTransport:
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


class RestartTransport(DiscoveryTransport):
    def __init__(self, setting_id: str = "spark", notebook_id: str = "first") -> None:
        super().__init__()
        self.setting_id = setting_id
        self.notebook_id = notebook_id
        self.requests: list[httpx.Request] = []
        self.put_entered = asyncio.Event()
        self.put_release = asyncio.Event()
        self.pause_put = False
        self.put_response = _ok({
            "id": setting_id, "name": "名称", "group": "spark", "status": "READY",
            "properties": {"private": "discarded"},
        })
        self.failure: httpx.HTTPError | None = None
        self.failure_stage = "PUT"

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.failure is not None and (
            request.method == self.failure_stage or request.url.path == self.failure_stage
        ):
            raise self.failure
        if request.method == "PUT":
            self.paths.append(request.url.path)
            self.put_entered.set()
            if self.pause_put:
                await self.put_release.wait()
            return self.put_response
        result = await super().handle_async_request(request)
        if "/notebook/" in request.url.path:
            return _ok({"id": self.notebook_id})
        return result


def contextual_adapter(
    transport: RestartTransport, *socket_items: LifecycleSocket, **settings: object,
) -> tuple[ZeppelinHttpClient, DiscoverySockets]:
    sockets = DiscoverySockets(*socket_items)
    return ZeppelinHttpClient(
        settings=_settings(**settings), secrets=_secrets(), transport=transport,
        websocket_connector=sockets,
    ), sockets


def selected_socket(**kwargs: str) -> LifecycleSocket:
    socket = LifecycleSocket(**kwargs)
    socket.frames = [response([binding(id="spark", selected=True)])]
    return socket


@pytest.mark.parametrize("notebook_id", ["first", "2/n%2F?x=# 中"])
async def test_contextual_restart_uses_fresh_selected_binding_and_exact_single_put(
    notebook_id: str,
) -> None:
    setting_id = "2/a%2F?x=# 中"
    transport = RestartTransport(setting_id, notebook_id)
    first, second = selected_socket(), selected_socket()
    first.frames = [response([binding(id=setting_id, selected=True)])]
    second.frames = [response([])]
    adapter, sockets = contextual_adapter(transport, first, second)
    result = await adapter.restart_interpreter(setting_id, notebook_id)
    assert result.model_dump() == {
        "setting_id": setting_id, "name": "名称", "group": "spark", "status": "READY",
    }
    with pytest.raises(ZeppelinGatewayError) as failure:
        await adapter.restart_interpreter(setting_id, notebook_id)
    assert failure.value.tool_error.category == ErrorCategory.INVALID_INPUT
    assert [request.method for request in transport.requests] == [
        "POST", "GET", "GET", "PUT", "GET", "GET",
    ]
    put = transport.requests[3]
    assert put.url.raw_path == (
        "/api/interpreter/setting/restart/" + quote(setting_id, safe="")
    ).encode()
    assert json.loads(put.content) == {"noteId": notebook_id}
    assert transport.tickets == sockets.calls == 2
    assert first.sent[0]["data"] == {"noteId": notebook_id}
    assert first.closes == second.closes == 1
    await adapter.close()


@pytest.mark.parametrize("bindings,category", [
    ([], ErrorCategory.INVALID_INPUT),
    ([binding(id="other", selected=True)], ErrorCategory.INVALID_INPUT),
    ([binding(id="spark", selected=False)], ErrorCategory.INVALID_INPUT),
    ([binding(id="Spark", selected=True)], ErrorCategory.INVALID_INPUT),
    ([binding(id="spark"), binding(id="spark")], ErrorCategory.UNEXPECTED_RESPONSE),
])
async def test_contextual_restart_membership_failure_never_puts(
    bindings: object, category: ErrorCategory,
) -> None:
    transport = RestartTransport()
    socket = selected_socket()
    socket.frames = [response(bindings)]
    adapter, sockets = contextual_adapter(transport, socket)
    with pytest.raises(ZeppelinGatewayError) as failure:
        await adapter.restart_interpreter("spark", "first")
    error = failure.value.tool_error
    assert (error.category, error.operation, error.retryable) == (
        category, ToolOperation.RESTART_INTERPRETER, False,
    )
    assert error.identifiers == {"setting_id": "spark", "notebook_id": "first"}
    assert all(request.method != "PUT" for request in transport.requests)
    assert sockets.calls == 1
    await adapter.close()


@pytest.mark.parametrize("stage", ["/api/login", "/api/notebook/first", "/api/security/ticket",
                                  "PUT"])
@pytest.mark.parametrize("exception,category", [
    (httpx.ReadTimeout("private"), ErrorCategory.TIMEOUT),
    (httpx.ConnectError("private"), ErrorCategory.CONNECTION_FAILED),
    (httpx.WriteTimeout("private"), ErrorCategory.TIMEOUT),
])
async def test_contextual_restart_transport_failure_is_never_retryable_or_repeated(
    stage: str, exception: httpx.HTTPError, category: ErrorCategory,
) -> None:
    transport = RestartTransport()
    transport.failure, transport.failure_stage = exception, stage
    adapter, sockets = contextual_adapter(transport, selected_socket())
    with pytest.raises(ZeppelinGatewayError) as failure:
        await adapter.restart_interpreter("spark", "first")
    error = failure.value.tool_error
    assert (error.category, error.operation, error.retryable) == (
        category, ToolOperation.RESTART_INTERPRETER, False,
    )
    assert error.identifiers == {"setting_id": "spark", "notebook_id": "first"}
    assert sum(request.method == "PUT" for request in transport.requests) == int(stage == "PUT")
    assert sockets.calls == int(stage == "PUT")
    assert "private" not in str(failure.value)
    await adapter.close()


@pytest.mark.parametrize("status,category", [
    (401, ErrorCategory.AUTHENTICATION_FAILED), (403, ErrorCategory.PERMISSION_DENIED),
    (404, ErrorCategory.UPSTREAM_ERROR), (500, ErrorCategory.UPSTREAM_ERROR),
    (302, ErrorCategory.UPSTREAM_ERROR),
])
async def test_contextual_restart_put_http_mapping_without_fallback(
    status: int, category: ErrorCategory,
) -> None:
    transport = RestartTransport()
    transport.put_response = httpx.Response(status, headers={"location": "https://other.invalid"})
    adapter, sockets = contextual_adapter(transport, selected_socket())
    with pytest.raises(ZeppelinGatewayError) as failure:
        await adapter.restart_interpreter("spark", "first")
    assert failure.value.tool_error.category == category
    assert not failure.value.tool_error.retryable
    assert sum(request.method == "PUT" for request in transport.requests) == 1
    assert sockets.calls == 1
    await adapter.close()


@pytest.mark.parametrize("explicit_null", [False, True])
@pytest.mark.parametrize("failure,category,retryable", [
    (None, None, False), (401, ErrorCategory.AUTHENTICATION_FAILED, False),
    (403, ErrorCategory.AUTHENTICATION_FAILED, False), (404, ErrorCategory.UPSTREAM_ERROR, False),
    (500, ErrorCategory.UPSTREAM_ERROR, False),
    (httpx.ReadTimeout("private"), ErrorCategory.TIMEOUT, True),
    (httpx.ConnectError("private"), ErrorCategory.CONNECTION_FAILED, True),
])
async def test_legacy_restart_retains_bodyless_path_and_error_metadata(
    explicit_null: bool, failure: int | httpx.HTTPError | None,
    category: ErrorCategory | None, retryable: bool,
) -> None:
    transport = RestartTransport()
    if isinstance(failure, int):
        transport.put_response = httpx.Response(failure)
    elif failure is not None:
        transport.failure = failure
    adapter, sockets = contextual_adapter(transport, base_url="https://zep.example/custom")
    try:
        if explicit_null:
            result = await adapter.restart_interpreter("spark", None)
        else:
            result = await adapter.restart_interpreter("spark")
        assert category is None and result.setting_id == "spark"
    except ZeppelinGatewayError as error:
        assert (error.tool_error.category, error.tool_error.retryable) == (category, retryable)
        assert error.tool_error.operation == ToolOperation.RESTART_INTERPRETER
    assert [request.method for request in transport.requests] == ["POST", "PUT"]
    assert transport.requests[-1].content == b""
    assert sockets.calls == 0
    await adapter.close()


@pytest.mark.parametrize("context", [None, "first"])
@pytest.mark.parametrize("field", ["id", "name", "group", "status"])
@pytest.mark.parametrize("value", [None, 1, True, [], {}, "", "bad\ntext", "bad\x7ftext",
                                  "x" * 257])
async def test_restart_rejects_non_string_empty_control_or_oversized_result_fields(
    context: str | None, field: str, value: object,
) -> None:
    transport = RestartTransport()
    body: dict[str, object] = {"id": "spark", "name": "名称", "group": "spark", "status": "READY"}
    body[field] = value
    transport.put_response = _ok(body)
    adapter, _ = contextual_adapter(transport, selected_socket(), max_opaque_id_chars=256)
    with pytest.raises(ZeppelinGatewayError) as failure:
        await adapter.restart_interpreter("spark", context)
    error = failure.value.tool_error
    assert (error.category, error.operation, error.retryable) == (
        ErrorCategory.UNEXPECTED_RESPONSE, ToolOperation.RESTART_INTERPRETER, False,
    )
    assert sum(request.method == "PUT" for request in transport.requests) == 1
    await adapter.close()


@pytest.mark.parametrize("context", [None, "first"])
@pytest.mark.parametrize("body", [
    {"id": "other", "name": "n", "group": "g", "status": "s"},
    {"id": "spark", "name": "n", "group": "g"},
])
async def test_restart_rejects_mismatched_or_missing_result_without_repeat(
    context: str | None, body: dict[str, str],
) -> None:
    transport = RestartTransport()
    transport.put_response = _ok(body)
    adapter, _ = contextual_adapter(transport, selected_socket())
    with pytest.raises(ZeppelinGatewayError) as failure:
        await adapter.restart_interpreter("spark", context)
    assert failure.value.tool_error.category == ErrorCategory.UNEXPECTED_RESPONSE
    assert not failure.value.tool_error.retryable
    assert sum(request.method == "PUT" for request in transport.requests) == 1
    await adapter.close()


@pytest.mark.parametrize("context", [None, "first"])
@pytest.mark.parametrize("overflow", [0, 1])
async def test_restart_result_budget_counts_complete_compact_utf8(
    context: str | None, overflow: int,
) -> None:
    expected = {"setting_id": "spark", "name": "名称", "group": "spark", "status": "READY"}
    byte_count = len(json.dumps(expected, ensure_ascii=False, separators=(",", ":")).encode())
    transport = RestartTransport()
    adapter, _ = contextual_adapter(
        transport, selected_socket(), max_result_bytes=byte_count - overflow,
    )
    if overflow:
        with pytest.raises(ZeppelinGatewayError) as failure:
            await adapter.restart_interpreter("spark", context)
        assert failure.value.tool_error.category == ErrorCategory.UNEXPECTED_RESPONSE
        assert not failure.value.tool_error.retryable
    else:
        assert (await adapter.restart_interpreter("spark", context)).model_dump() == expected
    assert sum(request.method == "PUT" for request in transport.requests) == 1
    await adapter.close()


@pytest.mark.parametrize("body", [
    {"id": "spark", "name": 123, "group": "g", "status": "s"},
    {"id": "other", "name": "n", "group": "g", "status": "s"},
    {"id": "spark", "name": "", "group": "g", "status": "s"},
])
async def test_legacy_restart_strict_response_regression(body: dict[str, object]) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _ok(body)

    adapter = _adapter(httpx.MockTransport(handler))
    try:
        with pytest.raises(ZeppelinGatewayError) as failure:
            await adapter.restart_interpreter("spark")
        assert failure.value.tool_error.category == ErrorCategory.UNEXPECTED_RESPONSE
        assert len(requests) == 1
    finally:
        await adapter.close()


async def test_contextual_restart_single_deadline_includes_lock_all_stages_and_put(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()
    now = loop.time()
    monkeypatch.setattr(loop, "time", lambda: now)
    transport = RestartTransport()
    transport.pause = "/api/login"
    transport.pause_put = True
    socket = selected_socket(pause="connect")
    adapter, _ = contextual_adapter(transport, socket, request_timeout_seconds=10)
    lock = asyncio.Lock()
    monkeypatch.setattr(adapter, "_discovery_lock", lock)
    await lock.acquire()
    task = asyncio.create_task(adapter.restart_interpreter("spark", "first"))
    await asyncio.sleep(0)
    now += 1
    lock.release()
    for path, following in (("/api/login", "/api/notebook/first"),
                            ("/api/notebook/first", "/api/security/ticket"),
                            ("/api/security/ticket", "")):
        await transport.entered[path].wait()
        now += 1
        transport.pause = following
        transport.release[path].set()
    for stage, following in (("connect", "send"), ("send", "receive"),
                              ("receive", "close"), ("close", "")):
        await socket.entered[stage].wait()
        now += 1
        socket.pause = following
        socket.release[stage].set()
    await transport.put_entered.wait()
    assert socket.calls[0]["open_timeout"] == 6
    now += 2.01
    with pytest.raises(ZeppelinGatewayError) as failure:
        await task
    error = failure.value.tool_error
    assert (error.category, error.operation, error.retryable) == (
        ErrorCategory.TIMEOUT, ToolOperation.RESTART_INTERPRETER, False,
    )
    assert error.identifiers == {"setting_id": "spark", "notebook_id": "first"}
    assert sum(request.method == "PUT" for request in transport.requests) == 1
    assert not lock.locked()
    assert socket.running == set()
    await adapter.close()


async def test_contextual_restart_lock_wait_expires_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()
    now = loop.time()
    monkeypatch.setattr(loop, "time", lambda: now)
    transport = RestartTransport()
    adapter, _ = contextual_adapter(transport, request_timeout_seconds=10)
    lock = asyncio.Lock()
    monkeypatch.setattr(adapter, "_discovery_lock", lock)
    await lock.acquire()
    task = asyncio.create_task(adapter.restart_interpreter("spark", "first"))
    await asyncio.sleep(0)
    now += 10.01
    with pytest.raises(ZeppelinGatewayError) as failure:
        await task
    assert failure.value.tool_error.category == ErrorCategory.TIMEOUT
    assert not failure.value.tool_error.retryable
    assert transport.requests == []
    lock.release()
    await adapter.close()


@pytest.mark.parametrize("shutdown", [False, True])
@pytest.mark.parametrize("stage", ["lock", "http", "connect", "send", "receive", "close", "put"])
async def test_contextual_restart_cancellation_and_shutdown_own_all_work(
    shutdown: bool, stage: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tasks_before = asyncio.all_tasks()
    transport = RestartTransport()
    transport.pause = "/api/login" if stage == "http" else ""
    transport.pause_put = stage == "put"
    socket = selected_socket(pause=stage)
    adapter, _ = contextual_adapter(transport, socket)
    lock = asyncio.Lock()
    monkeypatch.setattr(adapter, "_discovery_lock", lock)
    if stage == "lock":
        await lock.acquire()
    task = asyncio.create_task(adapter.restart_interpreter("spark", "first"))
    if stage == "lock":
        await asyncio.sleep(0)
    elif stage == "http":
        await transport.entered["/api/login"].wait()
    elif stage == "put":
        await transport.put_entered.wait()
    else:
        await socket.entered[stage].wait()
    close: asyncio.Task[None] | None = None
    if shutdown:
        close = asyncio.create_task(adapter.close())
        await asyncio.sleep(0)
    else:
        task.cancel()
    if stage == "close":
        socket.release["close"].set()
    with pytest.raises(asyncio.CancelledError):
        await task
    if shutdown:
        assert close is not None
        await close
        with pytest.raises(asyncio.CancelledError):
            await adapter.restart_interpreter("spark", "first")
    if stage == "lock":
        lock.release()
    assert not lock.locked()
    assert socket.running == set()
    assert sum(request.method == "PUT" for request in transport.requests) == int(stage == "put")
    await adapter.close()
    assert asyncio.all_tasks() == tasks_before


async def test_contextual_restart_keeps_lock_through_put_and_waiter_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RestartTransport()
    transport.pause_put = True
    socket = selected_socket()
    adapter, sockets = contextual_adapter(transport, socket)
    lock = asyncio.Lock()
    monkeypatch.setattr(adapter, "_discovery_lock", lock)
    active = asyncio.create_task(adapter.restart_interpreter("spark", "first"))
    await transport.put_entered.wait()
    waiter = asyncio.create_task(adapter.restart_interpreter("spark", "second"))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert not active.done()
    assert lock.locked()
    assert sockets.calls == 1 and transport.tickets == 1
    transport.put_release.set()
    assert (await active).setting_id == "spark"
    await adapter.close()


@pytest.mark.parametrize("stage", ["login", "notebook/first", "security/ticket",
                                  "connect", "send", "receive", "close"])
async def test_contextual_restart_discovery_deadline_never_falls_back(
    stage: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tasks_before = asyncio.all_tasks()
    loop = asyncio.get_running_loop()
    now = loop.time()
    monkeypatch.setattr(loop, "time", lambda: now)
    transport = RestartTransport()
    socket = selected_socket(pause=stage)
    transport.pause = f"/api/{stage}"
    adapter, sockets = contextual_adapter(transport, socket, request_timeout_seconds=10)
    caller = asyncio.create_task(adapter.restart_interpreter("spark", "first"))
    if transport.pause in transport.entered:
        await transport.entered[transport.pause].wait()
    else:
        await socket.entered[stage].wait()
    now += 10.01
    with pytest.raises(ZeppelinGatewayError) as failure:
        await caller
    assert (failure.value.tool_error.category, failure.value.tool_error.retryable) == (
        ErrorCategory.TIMEOUT, False,
    )
    assert failure.value.tool_error.operation == ToolOperation.RESTART_INTERPRETER
    assert all(request.method != "PUT" for request in transport.requests)
    assert sockets.calls <= 1 and socket.running == set()
    await adapter.close()
    assert asyncio.all_tasks() == tasks_before


@pytest.mark.parametrize("frame,category", [
    ("invalid", ErrorCategory.UNEXPECTED_RESPONSE),
    ('{"op":"SESSION_LOGOUT"}', ErrorCategory.AUTHENTICATION_FAILED),
    ('{"op":"ERROR_INFO","data":{"info":"private"}}', ErrorCategory.UPSTREAM_ERROR),
])
async def test_contextual_restart_socket_failures_keep_restart_context(
    frame: str, category: ErrorCategory,
) -> None:
    setting_id, notebook_id = "s" * 300, "n" * 300
    transport = RestartTransport(setting_id, notebook_id)
    socket = selected_socket()
    socket.frames = [frame]
    adapter, sockets = contextual_adapter(transport, socket)
    with pytest.raises(ZeppelinGatewayError) as failure:
        await adapter.restart_interpreter(setting_id, notebook_id)
    error = failure.value.tool_error
    assert (error.category, error.operation, error.retryable, error.identifiers) == (
        category, ToolOperation.RESTART_INTERPRETER, False, {},
    )
    assert all(request.method != "PUT" for request in transport.requests)
    assert sockets.calls == 1
    await adapter.close()


@pytest.mark.parametrize("context", [None, "first"])
async def test_restart_accepts_exact_field_bounds_and_long_opaque_id(context: str | None) -> None:
    setting_id = "s" * 300
    transport = RestartTransport(setting_id)
    transport.put_response = _ok({"id": setting_id, "name": "n" * 256,
                                  "group": "g" * 256, "status": "s" * 256})
    socket = selected_socket()
    socket.frames = [response([binding(id=setting_id)])]
    adapter, _ = contextual_adapter(transport, socket, max_opaque_id_chars=300)
    result = await adapter.restart_interpreter(setting_id, context)
    assert result.setting_id == setting_id
    assert (len(result.name), len(result.group), len(result.status)) == (256, 256, 256)
    await adapter.close()


async def test_contextual_restart_rejects_ambiguous_mount_before_login() -> None:
    transport = RestartTransport()
    adapter, sockets = contextual_adapter(transport, base_url="https://zep.example/custom")
    with pytest.raises(ZeppelinGatewayError) as failure:
        await adapter.restart_interpreter("spark", "first")
    assert failure.value.tool_error.category == ErrorCategory.CONFIG_ERROR
    assert failure.value.tool_error.operation == ToolOperation.RESTART_INTERPRETER
    assert not failure.value.tool_error.retryable
    assert transport.requests == [] and sockets.calls == 0
    await adapter.close()


@pytest.mark.parametrize("setting_id,encoded", [(".", b"%2E"), ("..", b"%2E%2E")])
@pytest.mark.parametrize("notebook_id", [None, "first"])
async def test_restart_dot_segment_is_sent_as_one_data_path_segment(
    setting_id: str, encoded: bytes, notebook_id: str | None,
) -> None:
    transport = RestartTransport(setting_id)
    socket = selected_socket()
    socket.frames = [response([binding(id=setting_id, selected=True)])]
    adapter, _ = contextual_adapter(transport, socket)
    try:
        assert (await adapter.restart_interpreter(setting_id, notebook_id)).setting_id == setting_id
        puts = [request for request in transport.requests if request.method == "PUT"]
        assert len(puts) == 1
        assert puts[0].url.raw_path == b"/api/interpreter/setting/restart/" + encoded
        if notebook_id is None:
            assert puts[0].content == b""
        else:
            assert json.loads(puts[0].content) == {"noteId": notebook_id}
    finally:
        await adapter.close()


@pytest.mark.parametrize("notebook_id,encoded", [(".", b"%2E"), ("..", b"%2E%2E")])
async def test_contextual_notebook_dot_segment_preserves_precheck_and_body(
    notebook_id: str, encoded: bytes,
) -> None:
    transport = RestartTransport(notebook_id=notebook_id)
    adapter, _ = contextual_adapter(transport, selected_socket())
    try:
        await adapter.restart_interpreter("spark", notebook_id)
        assert transport.requests[1].url.raw_path == b"/api/notebook/" + encoded
        assert json.loads(transport.requests[-1].content) == {"noteId": notebook_id}
    finally:
        await adapter.close()


class AbortReleasedPut(RestartTransport):
    """Model HTTP send cancellation that needs its transport forcibly released."""

    def __init__(self) -> None:
        super().__init__()
        self.abort_calls = 0
        self.send_cancelled = asyncio.Event()
        self.send_exited = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method != "PUT":
            return await super().handle_async_request(request)
        self.requests.append(request)
        self.put_entered.set()
        try:
            while not self.put_release.is_set():
                try:
                    await self.put_release.wait()
                except asyncio.CancelledError:
                    self.send_cancelled.set()
            return self.put_response
        finally:
            self.send_exited = True

    def abort(self) -> None:
        self.abort_calls += 1
        self.put_release.set()


@pytest.mark.parametrize("trigger", ["timeout", "cancel", "shutdown"])
async def test_contextual_abort_released_put_has_bounded_cleanup_and_no_orphan(
    trigger: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = asyncio.all_tasks()
    transport = AbortReleasedPut()
    adapter, sockets = contextual_adapter(
        transport, selected_socket(), request_timeout_seconds=0.02,
    )
    lock = asyncio.Lock()
    monkeypatch.setattr(adapter, "_discovery_lock", lock)
    caller = asyncio.create_task(adapter.restart_interpreter("spark", "first"))
    closer: asyncio.Task[None] | None = None
    await transport.put_entered.wait()
    if trigger == "cancel":
        caller.cancel()
    elif trigger == "shutdown":
        closer = asyncio.create_task(adapter.close())
    await transport.send_cancelled.wait()
    try:
        # A generous assertion deadline avoids scheduling-sensitive timing checks.
        # Production has only 20 ms of additional cleanup allowance.
        done, _ = await asyncio.wait((caller,), timeout=0.2)
        assert caller in done, "PUT cancellation never reached the required transport abort"
        if trigger == "timeout":
            with pytest.raises(ZeppelinGatewayError) as failure:
                await caller
            error = failure.value.tool_error
            assert (error.category, error.operation, error.retryable) == (
                ErrorCategory.TIMEOUT, ToolOperation.RESTART_INTERPRETER, False,
            )
            assert error.identifiers == {"setting_id": "spark", "notebook_id": "first"}
        else:
            with pytest.raises(asyncio.CancelledError):
                await caller
        if closer is not None:
            done, _ = await asyncio.wait((closer,), timeout=0.2)
            assert closer in done
            await closer
        assert transport.abort_calls == 1 and transport.send_exited
        assert not lock.locked()
        assert sockets.calls == 1
        assert sum(request.method == "PUT" for request in transport.requests) == 1
    finally:
        # Unblock the old implementation so functional RED itself leaks no work.
        if not transport.send_exited:
            transport.abort()
        await asyncio.gather(caller, return_exceptions=True)
        if closer is not None:
            await closer
        await adapter.close()
    assert asyncio.all_tasks() == before


@pytest.mark.parametrize("abort_behavior", ["raises", "no-op"])
@pytest.mark.parametrize("trigger", ["timeout", "cancel", "shutdown"])
async def test_contextual_failed_abort_keeps_owned_work_without_blocking_close(
    abort_behavior: str, trigger: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnreleasedPut(AbortReleasedPut):
        def __init__(self) -> None:
            super().__init__()
            self.work: asyncio.Task[object] | None = None

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if request.method != "PUT":
                return await super().handle_async_request(request)
            self.work = asyncio.current_task()
            await super().handle_async_request(request)
            raise RuntimeError("private-late-send-failure")

        def abort(self) -> None:
            self.abort_calls += 1
            if abort_behavior == "raises":
                raise OSError("private-abort-failure")

    loop = asyncio.get_running_loop()
    before = asyncio.all_tasks()
    loop_errors: list[dict[str, object]] = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: loop_errors.append(context))
    transport = UnreleasedPut()
    adapter, _ = contextual_adapter(transport, selected_socket(), request_timeout_seconds=0.02)
    lock = asyncio.Lock()
    monkeypatch.setattr(adapter, "_discovery_lock", lock)
    caller = asyncio.create_task(adapter.restart_interpreter("spark", "first"))
    closer: asyncio.Task[None] | None = None
    try:
        await transport.put_entered.wait()
        if trigger == "cancel":
            caller.cancel()
        elif trigger == "shutdown":
            closer = asyncio.create_task(adapter.close())
        await transport.send_cancelled.wait()
        done, _ = await asyncio.wait((caller,), timeout=0.2)
        assert caller in done, "abort failure left the caller in an unbounded join"
        if trigger == "timeout":
            with pytest.raises(ZeppelinGatewayError) as failure:
                await caller
            assert failure.value.tool_error.category == ErrorCategory.TIMEOUT
            assert not failure.value.tool_error.retryable
        else:
            with pytest.raises(asyncio.CancelledError):
                await caller
        if closer is None:
            closer = asyncio.create_task(adapter.close())
        done, _ = await asyncio.wait((closer,), timeout=0.2)
        assert closer in done, "close still depends on the non-cooperative PUT"
        await closer
        assert not lock.locked()
        assert transport.abort_calls >= 1
        work = transport.work
        assert work is not None and not work.done()
        # Inspect the private owner to distinguish retention from silent detachment.
        tracked = adapter_module._http_work_tasks  # pyright: ignore[reportPrivateUsage]
        assert work in tracked, "the unfinished work lost its strong owner"
        assert asyncio.all_tasks() - before == {work}
        transport.put_release.set()
        await asyncio.wait((work,), timeout=0.2)
        assert work.done()
        await asyncio.sleep(0)
        assert work not in tracked
        transport.work = None
        del work
        gc.collect()
        await asyncio.sleep(0)
        assert loop_errors == []
    finally:
        transport.put_release.set()
        await asyncio.gather(caller, return_exceptions=True)
        if closer is not None:
            await closer
        await adapter.close()
        if transport.work is not None:
            await asyncio.gather(transport.work, return_exceptions=True)
        loop.set_exception_handler(previous_handler)
    assert asyncio.all_tasks() == before


@pytest.mark.parametrize("stage", ["/api/notebook/first", "PUT"])
@pytest.mark.parametrize("exception", [httpx.ReadError("private"), httpx.WriteError("private")])
async def test_contextual_read_write_failure_maps_connection_without_retry(
    stage: str, exception: httpx.HTTPError,
) -> None:
    transport = RestartTransport()
    transport.failure, transport.failure_stage = exception, stage
    adapter, sockets = contextual_adapter(transport, selected_socket())
    try:
        with pytest.raises(ZeppelinGatewayError) as failure:
            await adapter.restart_interpreter("spark", "first")
        error = failure.value.tool_error
        assert (error.category, error.operation, error.retryable) == (
            ErrorCategory.CONNECTION_FAILED, ToolOperation.RESTART_INTERPRETER, False,
        )
        assert error.identifiers == {"setting_id": "spark", "notebook_id": "first"}
        assert "private" not in str(failure.value)
        assert sockets.calls == int(stage == "PUT")
        assert sum(request.method == "PUT" for request in transport.requests) == int(stage == "PUT")
    finally:
        await adapter.close()


@pytest.mark.parametrize("explicit_null", [False, True])
@pytest.mark.parametrize("exception", [httpx.ReadError("private"), httpx.WriteError("private")])
async def test_legacy_read_write_failure_preserves_upstream_mapping(
    explicit_null: bool, exception: httpx.HTTPError,
) -> None:
    transport = RestartTransport()
    transport.failure = exception
    adapter, sockets = contextual_adapter(transport)
    try:
        with pytest.raises(ZeppelinGatewayError) as failure:
            if explicit_null:
                await adapter.restart_interpreter("spark", None)
            else:
                await adapter.restart_interpreter("spark")
        error = failure.value.tool_error
        assert (error.category, error.operation, error.retryable) == (
            ErrorCategory.UPSTREAM_ERROR, ToolOperation.RESTART_INTERPRETER, False,
        )
        assert sockets.calls == 0
        assert sum(request.method == "PUT" for request in transport.requests) == 1
    finally:
        await adapter.close()


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

        def abort(self) -> None:
            owned_socket.close()

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

    owned_socket, peer_socket = socket.socketpair()
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
        assert owned_socket.fileno() == -1, "retained closer still owns a live socket"
    finally:
        owned_socket.close()
        peer_socket.close()
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


@pytest.fixture
async def local_http_peer() -> AsyncIterator[str]:
    handlers: set[asyncio.Task[None]] = set()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        handlers.add(task)
        try:
            while True:
                headers = await reader.readuntil(b"\r\n\r\n")
                body = {
                    "principal": "fake-user", "ticket": "fake-ticket", "roles": "[]",
                } if b"/security/ticket " in headers else {"id": "first"}
                content = json.dumps({"status": "OK", "body": body}).encode()
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(content)).encode()
                    + b"\r\n\r\n" + content,
                )
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            handlers.discard(task)

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        yield f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/api"
    finally:
        server.close()
        await server.wait_closed()
        for task in tuple(handlers):
            task.cancel()
        await asyncio.gather(*tuple(handlers), return_exceptions=True)


class LocalNetworkStream(Protocol):
    def get_extra_info(self, info: str) -> socket.socket: ...


@pytest.mark.parametrize("trigger", ["timeout", "cancel", "shutdown"])
async def test_contextual_put_cleanup_aborts_real_httpx_socket_before_response(
    trigger: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = asyncio.all_tasks()
    put_received = asyncio.Event()
    peer_closed = asyncio.Event()
    writers: list[asyncio.StreamWriter] = []
    handlers: set[asyncio.Task[object]] = set()

    async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        handlers.add(task)
        writers.append(writer)
        try:
            while True:
                headers = await reader.readuntil(b"\r\n\r\n")
                if headers.startswith(b"PUT "):
                    put_received.set()
                    await reader.read()
                    peer_closed.set()
                    return
                body = {
                    "principal": "fake-user", "ticket": "fake-ticket", "roles": "[]",
                } if b"/security/ticket " in headers else {"id": "first"}
                content = json.dumps({"status": "OK", "body": body}).encode()
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(content)).encode()
                    + b"\r\n\r\n" + content,
                )
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            handlers.discard(task)

    class CancellationNeedsSocketAbort(httpx.AsyncHTTPTransport):
        def __init__(self) -> None:
            super().__init__()
            self.network: LocalNetworkStream | None = None
            self.cancelled = asyncio.Event()
            self.put_count = 0
            self.release_close = asyncio.Event()

        async def aclose(self) -> None:
            # Shutdown's ordinary client close must not substitute for abort.
            await self.release_close.wait()
            await super().aclose()

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if request.method != "PUT":
                result = await super().handle_async_request(request)
                self.network = result.extensions["network_stream"]
                return result
            self.put_count += 1
            work = asyncio.create_task(super().handle_async_request(request))
            try:
                return await asyncio.shield(work)
            except asyncio.CancelledError:
                self.cancelled.set()
                # Simulate cancellation cleanup waiting for an OS-level release.
                while not work.done():
                    try:
                        await asyncio.shield(work)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                if not work.cancelled():
                    work.exception()
                raise

    class LongHttpTimeoutGateway(ZeppelinHttpClient):
        async def _ensure_client(self) -> httpx.AsyncClient:
            client = await super()._ensure_client()
            # Prevent HTTPX's own timeout from substituting for the tested abort.
            client.timeout = httpx.Timeout(10)
            return client

    abort_calls = 0
    actual_abort = HttpResources.abort

    def counted_abort(resources: HttpResources) -> None:
        nonlocal abort_calls
        abort_calls += 1
        actual_abort(resources)

    monkeypatch.setattr(HttpResources, "abort", counted_abort)
    server = await asyncio.start_server(peer, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    transport = CancellationNeedsSocketAbort()
    adapter = LongHttpTimeoutGateway(
        settings=_settings(base_url=f"http://127.0.0.1:{port}/api", request_timeout_seconds=0.1),
        secrets=_no_secrets(), transport=transport,
        websocket_connector=DiscoverySockets(selected_socket()),
    )
    caller = asyncio.create_task(adapter.restart_interpreter("spark", "first"))
    closer: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(put_received.wait(), 1)
        assert transport.network is not None
        raw_socket = transport.network.get_extra_info("socket")
        assert raw_socket.fileno() >= 0
        if trigger == "cancel":
            caller.cancel()
        elif trigger == "shutdown":
            closer = asyncio.create_task(adapter.close())
        await asyncio.wait_for(transport.cancelled.wait(), 1)
        done, _ = await asyncio.wait((caller,), timeout=0.5)
        assert caller in done, "pre-response cancellation did not abort the owned HTTP socket"
        if trigger == "timeout":
            with pytest.raises(ZeppelinGatewayError) as failure:
                await caller
            assert failure.value.tool_error.category == ErrorCategory.TIMEOUT
        else:
            with pytest.raises(asyncio.CancelledError):
                await caller
        await asyncio.wait_for(peer_closed.wait(), 1)
        assert raw_socket.fileno() == -1
        assert abort_calls >= 1
        assert transport.put_count == 1
    finally:
        transport.release_close.set()
        for writer in writers:
            writer.close()
        await asyncio.gather(caller, return_exceptions=True)
        if closer is not None:
            await closer
        await adapter.close()
        await httpx.AsyncHTTPTransport.aclose(transport)
        server.close()
        await server.wait_closed()
        await asyncio.gather(*handlers, return_exceptions=True)
    assert asyncio.all_tasks() == before


class LocalSocketTransport(httpx.AsyncHTTPTransport):
    def __init__(self, *, expose_network: bool = True) -> None:
        super().__init__()
        self.expose_network = expose_network
        self.network: LocalNetworkStream | None = None
        self.close_entered = asyncio.Event()
        self.release_close = asyncio.Event()
        self.close_task: asyncio.Task[object] | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        result = await super().handle_async_request(request)
        self.network = result.extensions["network_stream"]
        if not self.expose_network:
            del result.extensions["network_stream"]
        return result

    async def aclose(self) -> None:
        self.close_task = asyncio.current_task()
        self.close_entered.set()
        while not self.release_close.is_set():
            try:
                await self.release_close.wait()
            except asyncio.CancelledError:
                continue
        await super().aclose()


@pytest.mark.parametrize("expose_network", [False, True])
async def test_http_client_deadline_force_closes_real_idle_connection(
    monkeypatch: pytest.MonkeyPatch, local_http_peer: str, expose_network: bool,
) -> None:
    transport = LocalSocketTransport(expose_network=expose_network)
    gateway = ZeppelinHttpClient(
        settings=_settings(base_url=local_http_peer), secrets=_no_secrets(), transport=transport,
        websocket_connector=DiscoverySockets(LifecycleSocket()),
    )
    assert await gateway.get_interpreter_bindings("first") == ()
    assert transport.network is not None
    raw_socket = transport.network.get_extra_info("socket")
    assert raw_socket.fileno() >= 0
    loop = asyncio.get_running_loop()
    now = loop.time()
    monkeypatch.setattr(loop, "time", lambda: now)
    first = asyncio.create_task(gateway.close())
    await transport.close_entered.wait()
    second = asyncio.create_task(gateway.close())
    await asyncio.sleep(0)
    now += 5.01
    for _ in range(30):
        await asyncio.sleep(0)
    try:
        assert first.done() and second.done()
        assert raw_socket.fileno() == -1, "shared client left its pooled socket open"
        assert transport.close_task is not None and not transport.close_task.done()
    finally:
        transport.release_close.set()
        await asyncio.gather(first, second, return_exceptions=True)
        if transport.close_task is not None:
            await transport.close_task


@pytest.mark.parametrize("close_failure", [False, True])
async def test_response_abort_closes_real_asyncio_transport_socket(
    monkeypatch: pytest.MonkeyPatch, local_http_peer: str, close_failure: bool,
) -> None:
    closing = asyncio.Event()
    release = asyncio.Event()
    network: LocalNetworkStream | None = None

    class BlockedStream(httpx.AsyncByteStream):
        def __init__(self, stream: httpx.AsyncByteStream) -> None:
            self.stream = stream

        async def __aiter__(self) -> AsyncIterator[bytes]:
            async for chunk in self.stream:
                yield chunk

        async def aclose(self) -> None:
            closing.set()
            if close_failure:
                raise OSError("close failed")
            await release.wait()
            await self.stream.aclose()

    class Transport(httpx.AsyncHTTPTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal network
            result = await super().handle_async_request(request)
            network = result.extensions["network_stream"]
            result.stream = BlockedStream(cast(httpx.AsyncByteStream, result.stream))
            if close_failure:
                result.status_code = 403
            return result

    transport = Transport()
    gateway = ZeppelinHttpClient(
        settings=_settings(base_url=local_http_peer), secrets=_no_secrets(), transport=transport,
        websocket_connector=DiscoverySockets(),
    )
    caller = asyncio.create_task(gateway.get_interpreter_bindings("first"))
    await closing.wait()
    assert network is not None
    raw_socket = network.get_extra_info("socket")
    try:
        if close_failure:
            with pytest.raises(ZeppelinGatewayError) as error:
                await caller
            assert error.value.tool_error.category == ErrorCategory.PERMISSION_DENIED
        else:
            loop = asyncio.get_running_loop()
            now = loop.time()
            monkeypatch.setattr(loop, "time", lambda: now)
            caller.cancel()
            await asyncio.sleep(0)
            now += 5.01
            with pytest.raises(asyncio.CancelledError):
                await caller
        assert raw_socket.fileno() == -1, "shutdown() left TransportSocket's fd open"
    finally:
        release.set()
        await asyncio.gather(caller, return_exceptions=True)
        await gateway.close()


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

    def close(self) -> None:
        self.aborts += 1
        self.closed = True
        self.release_close.set()


@pytest.mark.parametrize("shutdown", [False, True])
async def test_contextual_put_cancellation_owns_eof_stream_until_bounded_abort(
    shutdown: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RestartStream(EOFClosingStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield json.dumps({"status": "OK", "body": {
                "id": "spark", "name": "n", "group": "g", "status": "s",
            }}).encode()

    tasks_before = asyncio.all_tasks()
    loop = asyncio.get_running_loop()
    now = loop.time()
    monkeypatch.setattr(loop, "time", lambda: now)
    stream = RestartStream()
    transport = RestartTransport()
    transport.put_response = httpx.Response(
        200, stream=stream, extensions={"network_stream": stream},
    )
    adapter, _ = contextual_adapter(transport, selected_socket(), request_timeout_seconds=2)
    caller = asyncio.create_task(adapter.restart_interpreter("spark", "first"))
    await stream.closing.wait()
    closer: asyncio.Task[None] | None = None
    if shutdown:
        closer = asyncio.create_task(adapter.close())
    else:
        caller.cancel()
    await asyncio.sleep(0)
    now += 2.01
    with pytest.raises(asyncio.CancelledError):
        await caller
    if closer is not None:
        await closer
    assert stream.closed and stream.aborts == 1 and stream.close_calls == 1
    assert sum(request.method == "PUT" for request in transport.requests) == 1
    await adapter.close()
    assert asyncio.all_tasks() == tasks_before


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
        seen_paths.append(raw.decode())
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
    status, outputs, error, _truncated = await adapter.get_paragraph_result("nb1", "p1")
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
    status, outputs, error, _truncated = await adapter.get_paragraph_result("nb1", "p1")
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
        seen_paths.append(raw.decode())
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
        seen_paths.append(raw.decode())
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
    context = await adapter._prepare_discovery(  # pyright: ignore[reportPrivateUsage] - exercise private session lifecycle seam
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
        await adapter._prepare_discovery(  # pyright: ignore[reportPrivateUsage] - exercise private session lifecycle seam
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
    assert adapter._client is None  # pyright: ignore[reportPrivateUsage] - exercise private session lifecycle seam
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
    client = await adapter._ensure_client()  # pyright: ignore[reportPrivateUsage] - exercise private session lifecycle seam
    client.cookies.set(
        "other_domain", "other-secret", domain="other.example", path="/proxy"
    )

    context = await adapter._prepare_discovery(  # pyright: ignore[reportPrivateUsage] - exercise private session lifecycle seam
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
        await adapter._prepare_discovery(  # pyright: ignore[reportPrivateUsage] - exercise private session lifecycle seam
            "note",
            operation=ToolOperation.GET_INTERPRETER_BINDINGS,
            identifiers={"notebook_id": "note"},
        )

    assert error.value.tool_error.category == ErrorCategory.UPSTREAM_ERROR
    assert [request.url.host for request in requests] == ["zep.example", "zep.example"]
    assert all(request.url.query == b"" for request in requests)
    assert all(request.url.userinfo == b"" for request in requests)
    assert adapter._client is not None  # pyright: ignore[reportPrivateUsage] - exercise private session lifecycle seam
    assert adapter._client.follow_redirects is False  # pyright: ignore[reportPrivateUsage] - exercise private session lifecycle seam
    assert adapter._client._trust_env is False  # pyright: ignore[reportPrivateUsage] - exercise private session lifecycle seam
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
    assert adapter._client is None  # pyright: ignore[reportPrivateUsage] - exercise private session lifecycle seam
    contexts: list[_TicketContext] = []
    for _ in range(2):
        context = await adapter._prepare_discovery(  # pyright: ignore[reportPrivateUsage] - exercise private session lifecycle seam
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


@pytest.mark.parametrize(
    "sentinel",
    [
        "username-secret-sentinel",
        "password-secret-sentinel",
        "principal-secret-sentinel",
        "ticket-secret-sentinel",
        "roles-secret-sentinel",
        "cookie-secret-sentinel",
    ],
)
@pytest.mark.parametrize("field", ["id", "name", "interpreter"])
async def test_discovery_rejects_sensitive_substrings_in_every_public_binding_field(
    sentinel: str,
    field: str,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    username = "username-secret-sentinel"
    password = "password-secret-sentinel"
    principal = "principal-secret-sentinel"
    ticket = "ticket-secret-sentinel"
    role = "roles-secret-sentinel"
    cookie = "cookie-secret-sentinel"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/login":
            return httpx.Response(
                200, headers={"set-cookie": f"JSESSIONID={cookie}; Path=/"},
            )
        if request.url.path == "/api/notebook/note":
            return _ok({"id": "note", "paragraphs": [{"text": ticket}]})
        assert request.url.path == "/api/security/ticket"
        return _ok(_ticket(principal=principal, ticket=ticket, roles=json.dumps([role])))

    contaminated = f"clean-prefix-{sentinel}-clean-suffix"
    item = binding(id="clean-id", name="Clean", interpreters=[{"name": "clean"}])
    if field == "interpreter":
        item["interpreters"] = [{"name": contaminated}]
    else:
        item[field] = contaminated
    socket = LifecycleSocket()
    socket.frames = [response([binding(id="first-clean"), item])]
    gateway = ZeppelinHttpClient(
        settings=_settings(),
        secrets=ZeppelinSecrets.model_validate({"username": username, "password": password}),
        transport=_mock_transport(handler),
        websocket_connector=DiscoverySockets(socket),
    )
    caplog.set_level(logging.DEBUG)

    with pytest.raises(ZeppelinGatewayError) as error:
        await gateway.get_interpreter_bindings("note")

    captured = capsys.readouterr()
    serialized = json.dumps(error.value.tool_error.to_dict(secret_values=()), sort_keys=True)
    for secret in (username, password, principal, ticket, role, cookie):
        assert secret not in str(error.value)
        assert secret not in repr(error.value)
        assert secret not in serialized
        assert secret not in caplog.text
        assert secret not in captured.out
        assert secret not in captured.err
    assert error.value.tool_error.category == ErrorCategory.UNEXPECTED_RESPONSE
    assert socket.closes == 1
    await gateway.close()


@pytest.mark.parametrize(
    "cookie_header",
    [
        "bad name=cookie-secret-sentinel",
        "good=first-cookie-sentinel; bad name=cookie-secret-sentinel",
        'good=first-cookie-sentinel; broken="unterminated-cookie-sentinel',
    ],
)
async def test_discovery_rejects_invalid_or_partially_parsed_cookie_header_before_websocket(
    cookie_header: str,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/notebook/note":
            return _ok({"id": "note"})
        assert request.url.path == "/api/security/ticket"
        return _ok(_ticket())

    socket = LifecycleSocket()
    socket.frames = [response([binding(name="cookie-secret-sentinel")])]
    sockets = DiscoverySockets(socket)

    class HeaderClient(ZeppelinHttpClient):
        async def _ensure_client(self) -> httpx.AsyncClient:
            client = await super()._ensure_client()
            client.headers["cookie"] = cookie_header
            return client

    gateway = HeaderClient(
        settings=_settings(),
        secrets=_no_secrets(),
        transport=_mock_transport(handler),
        websocket_connector=sockets,
    )
    caplog.set_level(logging.DEBUG)

    with pytest.raises(ZeppelinGatewayError) as error:
        await gateway.get_interpreter_bindings("note")

    captured = capsys.readouterr()
    rendered = " ".join((str(error.value), repr(error.value), caplog.text,
                         captured.out, captured.err))
    assert error.value.tool_error.category == ErrorCategory.UNEXPECTED_RESPONSE
    assert error.value.tool_error.operation == ToolOperation.GET_INTERPRETER_BINDINGS
    assert error.value.tool_error.retryable is False
    assert sockets.calls == 0
    for sentinel in (
        "cookie-secret-sentinel", "first-cookie-sentinel", "unterminated-cookie-sentinel",
    ):
        assert sentinel not in rendered
    await gateway.close()


@pytest.mark.parametrize(
    "cookie_value",
    [
        "plain-cookie-sentinel",
        "quoted-cookie-sentinel",
        "escaped;cookie-sentinel",
        "semi;cookie-sentinel",
        "left=right-cookie-sentinel",
    ],
)
async def test_discovery_scans_every_value_from_complete_quoted_cookie_header(
    cookie_value: str,
) -> None:
    cookie_header = (
        'plain=plain-cookie-sentinel; quoted="quoted-cookie-sentinel"; '
        'escaped="escaped\\073cookie-sentinel"; semi="semi;cookie-sentinel"; '
        "equals=left=right-cookie-sentinel"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/notebook/note":
            return _ok({"id": "note"})
        assert request.url.path == "/api/security/ticket"
        return _ok(_ticket())

    socket = LifecycleSocket()
    socket.frames = [response([binding(name=f"prefix-{cookie_value}-suffix")])]
    sockets = DiscoverySockets(socket)

    class HeaderClient(ZeppelinHttpClient):
        async def _ensure_client(self) -> httpx.AsyncClient:
            client = await super()._ensure_client()
            client.headers["cookie"] = cookie_header
            return client

    gateway = HeaderClient(
        settings=_settings(),
        secrets=_no_secrets(),
        transport=_mock_transport(handler),
        websocket_connector=sockets,
    )

    with pytest.raises(ZeppelinGatewayError) as error:
        await gateway.get_interpreter_bindings("note")

    assert error.value.tool_error.category == ErrorCategory.UNEXPECTED_RESPONSE
    assert sockets.calls == 1
    assert socket.closes == 1
    assert cookie_value not in str(error.value)
    await gateway.close()


@pytest.mark.parametrize(
    ("roles", "public_name"),
    [("[]", "Public [] setting"), ('[""]', 'Public [""] setting')],
)
async def test_empty_decoded_roles_do_not_taint_clean_public_fields(
    roles: str,
    public_name: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/notebook/note":
            return _ok({"id": "note"})
        assert request.url.path == "/api/security/ticket"
        return _ok(_ticket(roles=roles))

    socket = LifecycleSocket()
    socket.frames = [response([binding(name=public_name)])]
    gateway = ZeppelinHttpClient(
        settings=_settings(),
        secrets=_no_secrets(),
        transport=_mock_transport(handler),
        websocket_connector=DiscoverySockets(socket),
    )

    result = await gateway.get_interpreter_bindings("note")

    assert result[0].name == public_name
    await gateway.close()


async def test_http_stream_and_client_close_failures_never_emit_sensitive_text(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stream_secret = "stream-close-secret-sentinel raw-body"
    client_secret = "client-close-secret-sentinel raw-header"
    loop_contexts: list[dict[str, object]] = []
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: loop_contexts.append(context))

    class SecretCloseStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b"denied-body-must-not-escape"

        async def aclose(self) -> None:
            raise OSError(stream_secret)

    class SecretCloseTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, stream=SecretCloseStream())

        async def aclose(self) -> None:
            raise OSError(client_secret)

    caplog.set_level(logging.DEBUG)
    gateway = ZeppelinHttpClient(
        settings=_settings(),
        secrets=_no_secrets(),
        transport=SecretCloseTransport(),
        websocket_connector=DiscoverySockets(),
    )
    try:
        with pytest.raises(ZeppelinGatewayError) as error:
            await gateway.get_interpreter_bindings("note")
        assert error.value.tool_error.category == ErrorCategory.PERMISSION_DENIED
        await gateway.close()
        for _ in range(3):
            await asyncio.sleep(0)
    finally:
        loop.set_exception_handler(previous_handler)

    captured = capsys.readouterr()
    rendered = " ".join((str(error.value), repr(error.value), caplog.text, captured.out,
                         captured.err, repr(loop_contexts)))
    assert stream_secret not in rendered
    assert client_secret not in rendered
    assert "denied-body-must-not-escape" not in rendered
    assert loop_contexts == []


@pytest.mark.parametrize("body", [None, [], "note", {}, {"id": 1}, {"id": "other"}])
async def test_discovery_rejects_notebook_body_without_exact_id(body: object) -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return _ok(body)

    adapter = _adapter(_mock_transport(handler))
    with pytest.raises(ZeppelinGatewayError) as error:
        await adapter._prepare_discovery(  # pyright: ignore[reportPrivateUsage] - exercise private session lifecycle seam
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
    paths: list[str] = []
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
        await adapter._prepare_discovery(  # pyright: ignore[reportPrivateUsage] - exercise private session lifecycle seam
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
        await adapter._prepare_discovery("note", operation=ToolOperation.GET_INTERPRETER_BINDINGS,  # pyright: ignore[reportPrivateUsage] - exercise private session lifecycle seam
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
        await adapter._prepare_discovery("note", operation=ToolOperation.GET_INTERPRETER_BINDINGS,  # pyright: ignore[reportPrivateUsage] - exercise private session lifecycle seam
                                         identifiers={"notebook_id": "note"})
    assert error.value.tool_error.category == ErrorCategory.UNEXPECTED_RESPONSE
    await adapter.close()


@pytest.mark.parametrize("allow_anonymous", [True, False])
async def test_discovery_anonymous_mode_requires_upstream_ticket(allow_anonymous: bool) -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/notebook/note":
            return _ok({"id": "note"})
        assert request.url.path == "/api/security/ticket"
        return _ok(_ticket(principal="anonymous")) if allow_anonymous else httpx.Response(401)

    adapter = _adapter(_mock_transport(handler))
    if allow_anonymous:
        context = await adapter._prepare_discovery(  # pyright: ignore[reportPrivateUsage] - exercise private session lifecycle seam
            "note", operation=ToolOperation.GET_INTERPRETER_BINDINGS,
            identifiers={"notebook_id": "note"})
        assert context.principal == "anonymous"
    else:
        with pytest.raises(ZeppelinGatewayError) as error:
            await adapter._prepare_discovery(  # pyright: ignore[reportPrivateUsage] - exercise private session lifecycle seam
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
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == f"/api/{stage}":
            return httpx.Response(200, stream=stream, headers=headers)
        return _ok({"id": "note"})

    adapter = _adapter(_mock_transport(handler), settings=_settings(max_response_bytes=128),
                       secrets=_secrets())
    with pytest.raises(ZeppelinGatewayError) as error:
        await adapter._prepare_discovery("note", operation=ToolOperation.RESTART_INTERPRETER,  # pyright: ignore[reportPrivateUsage] - exercise private session lifecycle seam
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
    adapter = _adapter(_mock_transport(lambda _request: httpx.Response(200, json=document)))
    with pytest.raises(ZeppelinGatewayError) as error:
        await adapter._prepare_discovery("note", operation=ToolOperation.GET_INTERPRETER_BINDINGS,  # pyright: ignore[reportPrivateUsage] - exercise private session lifecycle seam
                                         identifiers={"notebook_id": "note"})
    category = (ErrorCategory.UPSTREAM_ERROR if isinstance(document, dict)
                and cast(dict[str, object], document).get("status") == "ERROR"
                else ErrorCategory.UNEXPECTED_RESPONSE)
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
    adapter = _adapter(_mock_transport(lambda _request: httpx.Response(200, stream=stream)))
    with pytest.raises(ZeppelinGatewayError) as error:
        await adapter._prepare_discovery("n" * 300, operation=operation,  # pyright: ignore[reportPrivateUsage] - exercise private session lifecycle seam
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
    adapter = _adapter(_mock_transport(lambda _request: httpx.Response(403)), secrets=_secrets())
    with pytest.raises(ZeppelinGatewayError) as error:
        if operation == ToolOperation.LIST_NOTEBOOKS:
            await adapter.list_notebooks()
        else:
            await adapter.restart_interpreter("spark")
    assert error.value.tool_error.operation == operation
    assert error.value.tool_error.category == ErrorCategory.AUTHENTICATION_FAILED
    await adapter.close()
