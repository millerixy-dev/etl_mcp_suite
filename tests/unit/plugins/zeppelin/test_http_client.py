"""Zeppelin HTTP adapter mock-transport tests."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from urllib.parse import parse_qs

import httpx
import pytest

from mcp_stdio.core.errors import ErrorCategory, ToolOperation
from mcp_stdio.plugins.zeppelin.config import ZeppelinSecrets, ZeppelinSettings
from mcp_stdio.plugins.zeppelin.gateway import ZeppelinGatewayError
from mcp_stdio.plugins.zeppelin.http_client import ZeppelinHttpClient
from mcp_stdio.plugins.zeppelin.models import (
    CancelParagraphResult,
    ParagraphStatus,
    RestartInterpreterResult,
)


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
