"""Asynchronous Zeppelin HTTP adapter behind the gateway port."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

import httpx

from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation, safe_error_identifiers
from mcp_stdio.plugins.zeppelin.config import ZeppelinSecrets, ZeppelinSettings
from mcp_stdio.plugins.zeppelin.gateway import ZeppelinGatewayError
from mcp_stdio.plugins.zeppelin.models import (
    CancelParagraphResult,
    InterpreterBindingRecord,
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
from mcp_stdio.plugins.zeppelin.websocket_client import (
    SingleQueryConnection,
    SocketConnector,
    await_cleanup,
    query_bindings,
)

logger = logging.getLogger("mcp_stdio.zeppelin")

_ZEPPELIN_STATUS_OK = "OK"


@dataclass(frozen=True, slots=True, repr=False)
class _TicketContext:
    """Transient adapter-only authentication; never include its fields in repr."""

    principal: str
    ticket: str
    roles: str
    websocket_url: str
    origin: str
    cookie_header: str | None


@dataclass(frozen=True, slots=True)
class _DiscoveryTarget:
    websocket_url: str
    http_url: str
    origin: str


def _derive_discovery_target(base_url: str) -> _DiscoveryTarget:
    """Derive the documented same-origin Zeppelin WebSocket target."""
    parts = urlsplit(base_url)
    try:
        hostname = parts.hostname
        _ = parts.port
    except ValueError:
        raise ValueError("base URL has no unambiguous WebSocket mapping") from None
    websocket_scheme = {"http": "ws", "https": "wss"}.get(parts.scheme)
    prefix, separator, final_component = parts.path.rpartition("/")
    if (
        websocket_scheme is None
        or not parts.netloc
        or not hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or not separator
        or final_component != "api"
    ):
        raise ValueError("base URL has no unambiguous WebSocket mapping")
    websocket_path = f"{prefix}/ws"
    return _DiscoveryTarget(
        websocket_url=urlunsplit(
            (websocket_scheme, parts.netloc, websocket_path, "", "")
        ),
        http_url=urlunsplit((parts.scheme, parts.netloc, websocket_path, "", "")),
        origin=urlunsplit((parts.scheme, parts.netloc, "", "", "")),
    )


class ZeppelinHttpClient:
    """httpx-backed Zeppelin gateway with one lazy client per process."""

    def __init__(
        self,
        *,
        settings: ZeppelinSettings,
        secrets: ZeppelinSecrets,
        transport: httpx.AsyncBaseTransport | None = None,
        websocket_connector: SocketConnector = SingleQueryConnection,
    ) -> None:
        self._settings = settings
        self._secrets = secrets
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._authenticated = False
        self._closed = False
        self._websocket_connector = websocket_connector
        self._discovery_lock = asyncio.Lock()
        self._discoveries: set[asyncio.Task[tuple[InterpreterBindingRecord, ...]]] = set()
        self._close_task: asyncio.Task[None] | None = None

    async def get_interpreter_bindings(
        self, notebook_id: str,
    ) -> tuple[InterpreterBindingRecord, ...]:
        deadline = asyncio.get_running_loop().time() + self._settings.request_timeout_seconds
        if self._closed:
            raise asyncio.CancelledError
        cancelled = asyncio.Event()
        task = asyncio.create_task(self._serialized_discovery(notebook_id, deadline, cancelled))
        self._discoveries.add(task)
        try:
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled.set()
                task.cancel()
                try:
                    await await_cleanup(task)
                except (Exception, asyncio.CancelledError):
                    pass
                raise
        finally:
            self._discoveries.discard(task)

    async def _serialized_discovery(
        self, notebook_id: str, deadline: float, cancelled: asyncio.Event,
    ) -> tuple[InterpreterBindingRecord, ...]:
        operation = ToolOperation.GET_INTERPRETER_BINDINGS
        identifiers = {"notebook_id": notebook_id}
        acquisition = asyncio.create_task(self._discovery_lock.acquire())
        try:
            await asyncio.wait_for(
                asyncio.shield(acquisition),
                max(0, deadline - asyncio.get_running_loop().time()),
            )
            if self._closed or cancelled.is_set():
                raise asyncio.CancelledError
            result = await self._discover_locked(
                notebook_id, deadline=deadline, operation=operation, identifiers=identifiers,
                cancelled=cancelled,
            )
            if self._closed or cancelled.is_set():
                raise asyncio.CancelledError
            return result
        except asyncio.TimeoutError:
            raise self._gateway_error(ErrorCategory.TIMEOUT, operation, identifiers) from None
        finally:
            if not acquisition.done():
                acquisition.cancel()
            try:
                await await_cleanup(asyncio.gather(acquisition, return_exceptions=True))
            finally:
                if not acquisition.cancelled() and acquisition.exception() is None:
                    if acquisition.result():
                        self._discovery_lock.release()

    async def _discover_locked(
        self, notebook_id: str, *, deadline: float, operation: ToolOperation,
        identifiers: dict[str, str],
        cancelled: asyncio.Event | None = None,
    ) -> tuple[InterpreterBindingRecord, ...]:
        """Use only with the discovery lock held; never acquire it recursively."""
        preparation = asyncio.create_task(
            self._prepare_discovery(notebook_id, operation=operation, identifiers=identifiers),
        )
        try:
            context = await asyncio.wait_for(
                asyncio.shield(preparation),
                max(0, deadline - asyncio.get_running_loop().time()),
            )
        finally:
            if not preparation.done():
                preparation.cancel()
            # Python 3.10/3.11 wait_for must not detach a stream on a second cancel.
            await await_cleanup(asyncio.gather(preparation, return_exceptions=True))
        try:
            if self._closed or (cancelled is not None and cancelled.is_set()):
                raise asyncio.CancelledError
            return await query_bindings(
                url=context.websocket_url, origin=context.origin, principal=context.principal,
                ticket=context.ticket, roles=context.roles, cookie_header=context.cookie_header,
                notebook_id=notebook_id, max_response_bytes=self._settings.max_response_bytes,
                max_opaque_id_chars=self._settings.max_opaque_id_chars,
                request_timeout_seconds=self._settings.request_timeout_seconds,
                operation=operation, identifiers=identifiers, connector=self._websocket_connector,
                deadline=deadline,
            )
        finally:
            del context

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._settings.base_url,
                timeout=self._settings.request_timeout_seconds,
                transport=self._transport,
                trust_env=False,
                follow_redirects=False,
            )
        return self._client

    async def _ensure_authenticated(
        self,
        *,
        operation: ToolOperation,
        identifiers: dict[str, str],
        discovery: bool = False,
    ) -> httpx.AsyncClient:
        client = await self._ensure_client()
        if self._authenticated or self._secrets.username is None:
            return client
        username = self._secrets.username.get_secret_value()
        password = self._secrets.password
        assert password is not None
        await self._request(
            client,
            "POST",
            "/login",
            form_data={"userName": username, "password": password.get_secret_value()},
            operation=operation,
            identifiers=identifiers,
            expect_body=False,
            discovery=discovery,
        )
        self._authenticated = True
        return client

    async def _prepare_discovery(
        self,
        notebook_id: str,
        *,
        operation: ToolOperation,
        identifiers: dict[str, str],
    ) -> _TicketContext:
        """Check notebook readability and obtain fresh auth on the same session."""
        try:
            target = _derive_discovery_target(self._settings.base_url)
        except ValueError:
            raise self._gateway_error(
                ErrorCategory.CONFIG_ERROR,
                operation,
                identifiers,
                retryable=False,
            ) from None
        encoded_id = self._encode_id(notebook_id)
        client = await self._ensure_authenticated(
            operation=operation, identifiers=identifiers, discovery=True,
        )
        notebook = await self._request(
            client, "GET", f"/notebook/{encoded_id}", operation=operation,
            identifiers=identifiers, expect_body=True, discovery=True, notebook_precheck=True,
        )
        if (
            not isinstance(notebook, dict)
            or cast(dict[str, Any], notebook).get("id") != notebook_id
        ):
            raise self._gateway_error(ErrorCategory.UNEXPECTED_RESPONSE, operation, identifiers)
        del notebook
        body = await self._request(
            client, "GET", "/security/ticket", operation=operation,
            identifiers=identifiers, expect_body=True, discovery=True,
        )
        if not isinstance(body, dict):
            raise self._gateway_error(ErrorCategory.UNEXPECTED_RESPONSE, operation, identifiers)
        fields: list[str] = []
        for key in ("principal", "ticket", "roles"):
            value = cast(dict[str, Any], body).get(key)
            if not isinstance(value, str) or not value:
                raise self._gateway_error(ErrorCategory.UNEXPECTED_RESPONSE, operation, identifiers)
            try:
                byte_length = len(value.encode("utf-8"))
            except UnicodeError:
                raise self._gateway_error(
                    ErrorCategory.UNEXPECTED_RESPONSE, operation, identifiers,
                ) from None
            if byte_length > self._settings.max_response_bytes:
                raise self._gateway_error(ErrorCategory.UNEXPECTED_RESPONSE, operation, identifiers)
            fields.append(value)
        principal, ticket, roles = fields
        try:
            decoded_roles: object = json.loads(roles)
        except (ValueError, RecursionError):
            raise self._gateway_error(
                ErrorCategory.UNEXPECTED_RESPONSE, operation, identifiers,
            ) from None
        if not isinstance(decoded_roles, list) or not all(
            isinstance(role, str) for role in cast(list[object], decoded_roles)
        ):
            raise self._gateway_error(ErrorCategory.UNEXPECTED_RESPONSE, operation, identifiers)
        cookie_header = client.build_request("GET", target.http_url).headers.get("cookie")
        return _TicketContext(
            principal=principal,
            ticket=ticket,
            roles=roles,
            websocket_url=target.websocket_url,
            origin=target.origin,
            cookie_header=cookie_header,
        )

    async def list_notebooks(self) -> tuple[NotebookTreeNode, ...]:
        client = await self._ensure_authenticated(
            operation=ToolOperation.LIST_NOTEBOOKS, identifiers={},
        )
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
        client = await self._ensure_authenticated(
            operation=ToolOperation.CREATE_NOTEBOOK, identifiers={},
        )
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
        client = await self._ensure_authenticated(
            operation=ToolOperation.ADD_PARAGRAPH, identifiers={"notebook_id": notebook_id},
        )
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
        client = await self._ensure_authenticated(
            operation=ToolOperation.RUN_PARAGRAPH,
            identifiers={"notebook_id": notebook_id, "paragraph_id": paragraph_id},
        )
        await self._request_json(
            client,
            "POST",
            f"/notebook/job/{encoded_nb}/{encoded_p}",
            json_payload=None,
            operation=ToolOperation.RUN_PARAGRAPH,
            identifiers={"notebook": notebook_id, "paragraph": paragraph_id},
        )
        return ParagraphStatus.PENDING

    async def cancel_paragraph(
        self, notebook_id: str, paragraph_id: str
    ) -> CancelParagraphResult:
        encoded_nb = self._encode_id(notebook_id)
        encoded_p = self._encode_id(paragraph_id)
        client = await self._ensure_authenticated(
            operation=ToolOperation.CANCEL_PARAGRAPH,
            identifiers={"notebook_id": notebook_id, "paragraph_id": paragraph_id},
        )
        await self._request_json(
            client,
            "DELETE",
            f"/notebook/job/{encoded_nb}/{encoded_p}",
            json_payload=None,
            operation=ToolOperation.CANCEL_PARAGRAPH,
            identifiers={"notebook_id": notebook_id, "paragraph_id": paragraph_id},
        )
        return CancelParagraphResult(notebook_id=notebook_id, paragraph_id=paragraph_id)

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
        client = await self._ensure_authenticated(
            operation=ToolOperation.GET_PARAGRAPH_RESULT,
            identifiers={"notebook_id": notebook_id, "paragraph_id": paragraph_id},
        )
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
        client = await self._ensure_authenticated(
            operation=ToolOperation.RESTART_INTERPRETER, identifiers={"setting_id": setting_id},
        )
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
        self._closed = True
        if self._close_task is None:
            deadline = asyncio.get_running_loop().time() + min(
                5.0, self._settings.request_timeout_seconds,
            )
            self._close_task = asyncio.create_task(self._close(deadline))
        await await_cleanup(self._close_task)

    async def _close(self, deadline: float) -> None:
        discoveries = tuple(self._discoveries)
        for task in discoveries:
            task.cancel()
        await asyncio.gather(*discoveries, return_exceptions=True)
        if self._client is not None:
            await self._close_http_resource(self._client, deadline=deadline)
            self._client = None

    async def _close_http_resource(
        self, resource: httpx.Response | httpx.AsyncClient, *, deadline: float | None = None,
    ) -> None:
        remaining = min(5.0, self._settings.request_timeout_seconds) if deadline is None else (
            max(0, deadline - asyncio.get_running_loop().time())
        )
        task = asyncio.create_task(resource.aclose())
        try:
            # Even with an exhausted allowance, initiate resource closure once.
            if remaining == 0:
                await asyncio.sleep(0)
            await asyncio.wait_for(task, remaining)
        except Exception:
            pass

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
        form_data: dict[str, str] | None = None,
        operation: ToolOperation,
        identifiers: dict[str, str],
        expect_body: bool,
        discovery: bool = False,
        notebook_precheck: bool = False,
    ) -> Any:
        try:
            if discovery:
                response = await client.send(
                    client.build_request(method, path, json=json_payload, data=form_data),
                    stream=True,
                )
                try:
                    self._check_http_status(
                        response, operation, identifiers, discovery=True,
                        notebook_precheck=notebook_precheck,
                    )
                    content = await self._read_bounded(response, operation, identifiers)
                finally:
                    await await_cleanup(asyncio.create_task(self._close_http_resource(response)))
            else:
                response = await client.request(method, path, json=json_payload, data=form_data)
                bounded = await self._bound_response(response)
                self._check_http_status(bounded, operation, identifiers)
                content = bounded.content
        except (httpx.ConnectTimeout, httpx.ReadTimeout):
            raise self._gateway_error(
                ErrorCategory.TIMEOUT, operation, identifiers,
                retryable=not (discovery and operation == ToolOperation.RESTART_INTERPRETER),
            ) from None
        except (httpx.ConnectError, httpx.RemoteProtocolError):
            raise self._gateway_error(
                ErrorCategory.CONNECTION_FAILED, operation, identifiers,
                retryable=not (discovery and operation == ToolOperation.RESTART_INTERPRETER),
            ) from None
        except httpx.HTTPError as exc:
            if discovery and isinstance(exc, httpx.TimeoutException):
                raise self._gateway_error(
                    ErrorCategory.TIMEOUT, operation, identifiers,
                    retryable=operation != ToolOperation.RESTART_INTERPRETER,
                ) from None
            raise self._gateway_error(
                ErrorCategory.UPSTREAM_ERROR, operation, identifiers
            ) from None

        if not expect_body:
            return None
        try:
            document: object = json.loads(content)
        except (ValueError, UnicodeError, RecursionError):
            raise self._gateway_error(
                ErrorCategory.UNEXPECTED_RESPONSE,
                operation,
                identifiers,
            ) from None
        if not isinstance(document, dict):
            raise self._gateway_error(ErrorCategory.UNEXPECTED_RESPONSE, operation, identifiers)
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

    def _check_http_status(
        self,
        response: httpx.Response,
        operation: ToolOperation,
        identifiers: dict[str, str],
        *,
        discovery: bool = False,
        notebook_precheck: bool = False,
    ) -> None:
        status = response.status_code
        if status == 401 or (status == 403 and not discovery):
            category = ErrorCategory.AUTHENTICATION_FAILED
        elif status == 403:
            category = ErrorCategory.PERMISSION_DENIED
        elif status == 404 and notebook_precheck:
            category = ErrorCategory.NOT_FOUND
        elif status >= 400 or (discovery and not 200 <= status < 300):
            category = ErrorCategory.UPSTREAM_ERROR
        else:
            return
        raise self._gateway_error(category, operation, identifiers)

    async def _read_bounded(
        self,
        response: httpx.Response,
        operation: ToolOperation,
        identifiers: dict[str, str],
    ) -> bytes:
        content = bytearray()
        async for chunk in response.aiter_bytes():
            if len(content) + len(chunk) > self._settings.max_response_bytes:
                raise self._gateway_error(ErrorCategory.UNEXPECTED_RESPONSE, operation, identifiers)
            content.extend(chunk)
        return bytes(content)

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
        *,
        retryable: bool | None = None,
    ) -> ZeppelinGatewayError:
        return ZeppelinGatewayError(
            ToolError.create(
                category=category,
                operation=operation,
                retryable=(category in (ErrorCategory.TIMEOUT, ErrorCategory.CONNECTION_FAILED)
                           if retryable is None else retryable),
                identifiers=safe_error_identifiers(operation, identifiers),
            )
        )
