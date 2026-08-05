"""Asynchronous Zeppelin HTTP adapter behind the gateway port."""

from __future__ import annotations

import logging
from typing import Any, cast

import httpx

from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation
from mcp_stdio.plugins.zeppelin.config import ZeppelinSecrets, ZeppelinSettings
from mcp_stdio.plugins.zeppelin.gateway import ZeppelinGatewayError
from mcp_stdio.plugins.zeppelin.models import (
    NotebookTreeNode,
    OutputItem,
    OutputKind,
    ParagraphStatus,
    RestartInterpreterResult,
    SafeErrorDetail,
    build_notebook_tree,
    normalize_paragraph_status,
    truncate_utf8,
    validate_opaque_id,
)

logger = logging.getLogger("mcp_stdio.zeppelin")

_ZEPPELIN_STATUS_OK = "OK"


class ZeppelinHttpClient:
    """httpx-backed Zeppelin gateway with one lazy client per process."""

    def __init__(
        self,
        *,
        settings: ZeppelinSettings,
        secrets: ZeppelinSecrets,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._secrets = secrets
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._authenticated = False
        self._closed = False

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._settings.base_url,
                timeout=self._settings.request_timeout_seconds,
                transport=self._transport,
                trust_env=False,
            )
        return self._client

    async def _ensure_authenticated(self) -> httpx.AsyncClient:
        client = await self._ensure_client()
        if self._authenticated or self._secrets.username is None:
            return client
        username = self._secrets.username.get_secret_value()
        password = self._secrets.password
        assert password is not None
        response = await self._request(
            client,
            "POST",
            "/login",
            content=f"userName={username}&password={password.get_secret_value()}",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            operation=ToolOperation.CREATE_NOTEBOOK,
            identifiers={},
            expect_body=False,
        )
        self._authenticated = True
        del response
        return client

    async def list_notebooks(self) -> tuple[NotebookTreeNode, ...]:
        client = await self._ensure_authenticated()
        body = await self._request_json(
            client,
            "GET",
            "/notebook",
            json_payload=None,
            operation=ToolOperation.LIST_NOTEBOOKS,
            identifiers={},
        )
        if not isinstance(body, list):
            raise self._gateway_error(
                ErrorCategory.UNEXPECTED_RESPONSE,
                ToolOperation.LIST_NOTEBOOKS,
                {},
            )
        entries: list[tuple[str, str]] = []
        raw_items = cast(list[object], body)
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            typed_item = cast(dict[str, Any], item)
            item_id = typed_item.get("id")
            item_path = typed_item.get("path")
            if isinstance(item_id, str) and isinstance(item_path, str):
                entries.append((item_id, item_path))
        return build_notebook_tree(tuple(entries))

    async def create_notebook(self, name: str) -> str:
        client = await self._ensure_authenticated()
        body = await self._request_json(
            client,
            "POST",
            "/notebook",
            json_payload={"name": name},
            operation=ToolOperation.CREATE_NOTEBOOK,
            identifiers={},
        )
        return self._require_string_body(body, "notebook ID")

    async def add_paragraph(
        self,
        notebook_id: str,
        title: str,
        body: str,
    ) -> str:
        encoded_nb = self._encode_id(notebook_id)
        client = await self._ensure_authenticated()
        result = await self._request_json(
            client,
            "POST",
            f"/notebook/{encoded_nb}/paragraph",
            json_payload={"title": title, "text": body},
            operation=ToolOperation.ADD_PARAGRAPH,
            identifiers={"notebook": notebook_id},
        )
        return self._require_string_body(result, "paragraph ID")

    async def run_paragraph(self, notebook_id: str, paragraph_id: str) -> ParagraphStatus:
        encoded_nb = self._encode_id(notebook_id)
        encoded_p = self._encode_id(paragraph_id)
        client = await self._ensure_authenticated()
        await self._request_json(
            client,
            "POST",
            f"/notebook/job/{encoded_nb}/{encoded_p}",
            json_payload=None,
            operation=ToolOperation.RUN_PARAGRAPH,
            identifiers={"notebook": notebook_id, "paragraph": paragraph_id},
        )
        return ParagraphStatus.PENDING

    async def get_paragraph_status(self, notebook_id: str, paragraph_id: str) -> ParagraphStatus:
        paragraph = await self._fetch_paragraph(notebook_id, paragraph_id)
        return normalize_paragraph_status(paragraph.get("status"))

    async def get_paragraph_result(
        self, notebook_id: str, paragraph_id: str
    ) -> tuple[ParagraphStatus, tuple[OutputItem, ...], SafeErrorDetail | None, bool]:
        paragraph = await self._fetch_paragraph(notebook_id, paragraph_id)
        status = normalize_paragraph_status(paragraph.get("status"))
        raw_results = paragraph.get("results")
        if not isinstance(raw_results, dict):
            raw_results = {}
        results = cast(dict[str, Any], raw_results)
        outputs: tuple[OutputItem, ...] = ()
        error: SafeErrorDetail | None = None
        truncated = False
        max_bytes = self._settings.max_result_bytes
        raw_msg = results.get("msg", [])
        if isinstance(raw_msg, list):
            items: list[OutputItem] = []
            msg_entries = cast(list[object], raw_msg)
            for raw_entry in msg_entries:
                if not isinstance(raw_entry, dict):
                    continue
                entry = cast(dict[str, Any], raw_entry)
                kind = self._map_output_kind(entry.get("type"))
                raw_data = entry.get("data", "")
                data = raw_data if isinstance(raw_data, str) else str(raw_data)
                text, was_truncated = truncate_utf8(data, max_bytes=max_bytes)
                if was_truncated:
                    truncated = True
                items.append(OutputItem(kind=kind, text=text))
            outputs = tuple(items)
        raw_exception = results.get("exception")
        if raw_exception is not None and str(raw_exception).strip():
            exc_text, was_truncated = truncate_utf8(str(raw_exception), max_bytes=max_bytes)
            if was_truncated:
                truncated = True
            error = SafeErrorDetail(message=exc_text)
        return status, outputs, error, truncated

    async def _fetch_paragraph(self, notebook_id: str, paragraph_id: str) -> dict[str, Any]:
        encoded_nb = self._encode_id(notebook_id)
        encoded_p = self._encode_id(paragraph_id)
        client = await self._ensure_authenticated()
        body = await self._request_json(
            client,
            "GET",
            f"/notebook/{encoded_nb}/paragraph/{encoded_p}",
            json_payload=None,
            operation=ToolOperation.GET_PARAGRAPH_RESULT,
            identifiers={"notebook": notebook_id, "paragraph": paragraph_id},
        )
        if not isinstance(body, dict):
            raise self._gateway_error(
                ErrorCategory.UNEXPECTED_RESPONSE,
                ToolOperation.GET_PARAGRAPH_RESULT,
                {},
            )
        return cast(dict[str, Any], body)

    async def restart_interpreter(self, setting_id: str) -> RestartInterpreterResult:
        encoded_id = self._encode_id(setting_id)
        client = await self._ensure_authenticated()
        body = await self._request_json(
            client,
            "PUT",
            f"/interpreter/setting/restart/{encoded_id}",
            json_payload=None,
            operation=ToolOperation.RESTART_INTERPRETER,
            identifiers={"setting_id": setting_id},
        )
        if not isinstance(body, dict):
            raise self._gateway_error(
                ErrorCategory.UNEXPECTED_RESPONSE,
                ToolOperation.RESTART_INTERPRETER,
                {"setting_id": setting_id},
            )
        typed_body = cast(dict[str, Any], body)
        try:
            return RestartInterpreterResult(
                setting_id=str(typed_body["id"]),
                name=str(typed_body["name"]),
                group=str(typed_body["group"]),
                status=str(typed_body["status"]),
            )
        except KeyError:
            raise self._gateway_error(
                ErrorCategory.UNEXPECTED_RESPONSE,
                ToolOperation.RESTART_INTERPRETER,
                {"setting_id": setting_id},
            ) from None

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                logger.debug("error closing zeppelin http client", exc_info=True)
            self._client = None

    def _encode_id(self, opaque_id: str) -> str:
        from urllib.parse import quote

        validated = validate_opaque_id(opaque_id, max_chars=self._settings.max_opaque_id_chars)
        return quote(validated, safe="")

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None,
        operation: ToolOperation,
        identifiers: dict[str, str],
    ) -> Any:
        return await self._request(
            client,
            method,
            path,
            json_payload=json_payload,
            operation=operation,
            identifiers=identifiers,
            expect_body=True,
        )

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
        content: str | None = None,
        headers: dict[str, str] | None = None,
        operation: ToolOperation,
        identifiers: dict[str, str],
        expect_body: bool,
    ) -> Any:
        try:
            response = await client.request(
                method,
                path,
                json=json_payload,
                content=content,
                headers=headers,
            )
        except httpx.ConnectTimeout:
            raise self._gateway_error(ErrorCategory.TIMEOUT, operation, identifiers) from None
        except httpx.ReadTimeout:
            raise self._gateway_error(ErrorCategory.TIMEOUT, operation, identifiers) from None
        except (httpx.ConnectError, httpx.RemoteProtocolError):
            raise self._gateway_error(
                ErrorCategory.CONNECTION_FAILED, operation, identifiers
            ) from None
        except httpx.HTTPError:
            raise self._gateway_error(
                ErrorCategory.UPSTREAM_ERROR, operation, identifiers
            ) from None

        bounded = await self._bound_response(response)
        if bounded.status_code == 401 or bounded.status_code == 403:
            raise self._gateway_error(
                ErrorCategory.AUTHENTICATION_FAILED,
                operation,
                identifiers,
            )
        if bounded.status_code >= 400:
            raise self._gateway_error(
                ErrorCategory.UPSTREAM_ERROR,
                operation,
                identifiers,
            )
        if not expect_body:
            return bounded
        try:
            document = bounded.json()
        except Exception:
            raise self._gateway_error(
                ErrorCategory.UNEXPECTED_RESPONSE,
                operation,
                identifiers,
            ) from None
        typed_doc = cast(dict[str, Any], document)
        status = typed_doc.get("status")
        if status is None:
            raise self._gateway_error(
                ErrorCategory.UNEXPECTED_RESPONSE, operation, identifiers
            ) from None
        if status != _ZEPPELIN_STATUS_OK:
            raise self._gateway_error(
                ErrorCategory.UPSTREAM_ERROR,
                operation,
                identifiers,
            )
        return typed_doc.get("body")

    async def _bound_response(self, response: httpx.Response) -> httpx.Response:
        max_bytes = self._settings.max_response_bytes
        content = response.content
        if len(content) > max_bytes:
            raise self._gateway_error(ErrorCategory.UNEXPECTED_RESPONSE, ToolOperation.RUNTIME, {})
        return response

    def _require_string_body(self, body: Any, label: str) -> str:
        if not isinstance(body, str):
            raise self._gateway_error(ErrorCategory.UNEXPECTED_RESPONSE, ToolOperation.RUNTIME, {})
        return body

    def _map_output_kind(self, raw: Any) -> OutputKind:
        if isinstance(raw, str):
            upper = raw.upper()
            for kind in OutputKind:
                if kind.value == upper:
                    return kind
        return OutputKind.TEXT

    def _gateway_error(
        self,
        category: ErrorCategory,
        operation: ToolOperation,
        identifiers: dict[str, str],
    ) -> ZeppelinGatewayError:
        return ZeppelinGatewayError(
            ToolError.create(
                category=category,
                operation=operation,
                retryable=category in (ErrorCategory.TIMEOUT, ErrorCategory.CONNECTION_FAILED),
                identifiers=identifiers,
            )
        )
