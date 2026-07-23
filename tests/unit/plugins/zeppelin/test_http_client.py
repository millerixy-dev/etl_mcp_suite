"""Zeppelin HTTP adapter mock-transport tests."""

from __future__ import annotations

import httpx
import pytest

from mcp_stdio.core.errors import ErrorCategory
from mcp_stdio.plugins.zeppelin.config import ZeppelinSecrets, ZeppelinSettings
from mcp_stdio.plugins.zeppelin.gateway import ZeppelinGatewayError
from mcp_stdio.plugins.zeppelin.http_client import ZeppelinHttpClient
from mcp_stdio.plugins.zeppelin.models import ParagraphStatus


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
    pid = await adapter.add_paragraph("note/1", "title", "spark", "body")
    assert pid == "paragraph_123"
    assert seen_paths[-1] == "/api/notebook/note%2F1/paragraph"
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


async def test_get_paragraph_result_error_state() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _ok(
            {
                "status": "ERROR",
                "results": {
                    "code": "ERROR",
                    "msg": [],
                    "exception": "boom",
                },
            }
        )

    adapter = _adapter(_mock_transport(handler))
    status, outputs, error, truncated = await adapter.get_paragraph_result("nb1", "p1")
    assert status is ParagraphStatus.ERROR
    assert outputs == ()
    assert error is not None
    assert "boom" in error.message
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
