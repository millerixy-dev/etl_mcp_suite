"""Zeppelin HTTP adapter mock-transport tests."""

from __future__ import annotations

import httpx
import pytest

from mcp_stdio.core.errors import ErrorCategory
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
