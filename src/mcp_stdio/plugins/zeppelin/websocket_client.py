"""One isolated, authenticated Zeppelin binding query over WebSocket."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from typing import Protocol, TypeVar, cast, runtime_checkable
from uuid import uuid4

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus
from websockets.typing import Origin

from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation, safe_error_identifiers
from mcp_stdio.plugins.zeppelin.gateway import ZeppelinGatewayError
from mcp_stdio.plugins.zeppelin.models import InterpreterBindingRecord, validate_opaque_id

_MAX_MESSAGES = 32
_MAX_BINDINGS = 256

# A standalone, disabled logger cannot inherit application debug handlers.
_transport_logger = logging.Logger("mcp_stdio.zeppelin.websocket.private")
_transport_logger.disabled = True
_transport_logger.propagate = False
_transport_logger.addHandler(logging.NullHandler())


class _Connection(Protocol):
    async def send(self, message: str) -> None: ...

    async def recv(self) -> str | bytes: ...


class SocketConnector(Protocol):
    def __call__(
        self,
        url: str,
        /,
        *,
        origin: Origin,
        additional_headers: dict[str, str] | None,
        proxy: None,
        compression: None,
        max_queue: int,
        max_size: int,
        open_timeout: float,
        close_timeout: float,
        logger: logging.Logger,
    ) -> AbstractAsyncContextManager[_Connection]: ...


class SingleQueryConnection(connect):
    """Disable the library's handshake redirects, including same-origin ones."""

    def process_redirect(self, exc: Exception) -> Exception:
        return exc

    def abort(self) -> None:
        if hasattr(self, "connection"):
            self.connection.transport.abort()


@runtime_checkable
class _Abortable(Protocol):
    def abort(self) -> None: ...


_T = TypeVar("_T")


async def await_cleanup(task: asyncio.Future[_T]) -> _T:
    """Join owned cleanup even on repeated cancellation, then preserve cancellation."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    if cancelled:
        # Consume a cleanup failure without replacing the caller's cancellation.
        if not task.cancelled():
            task.exception()
        raise asyncio.CancelledError
    return task.result()


class _BindingQuery:
    """Own the entire connect/send/receive task and one bounded cleanup task."""

    def __init__(
        self, context: AbstractAsyncContextManager[_Connection], *, payload: str,
        max_response_bytes: int, max_opaque_id_chars: int, cleanup_seconds: float,
    ) -> None:
        self._context = context
        self._connection: _Connection | None = None
        self._cleanup_seconds = cleanup_seconds
        self._aborted = False
        self._close_task: asyncio.Task[None] | None = None
        self.work = asyncio.create_task(self._exchange(
            payload, max_response_bytes, max_opaque_id_chars,
        ))

    async def _exchange(
        self, payload: str, max_response_bytes: int, max_opaque_id_chars: int,
    ) -> tuple[InterpreterBindingRecord, ...]:
        self._connection = await self._context.__aenter__()
        await self._connection.send(payload)
        return await _receive_bindings(
            self._connection, max_response_bytes=max_response_bytes,
            max_opaque_id_chars=max_opaque_id_chars,
        )

    def _abort(self) -> None:
        if self._aborted:
            return
        self._aborted = True
        try:
            if isinstance(self._context, _Abortable):
                self._context.abort()
        except Exception:
            pass

    async def _finish(self) -> None:
        await asyncio.gather(self.work, return_exceptions=True)
        if self._connection is None:
            self._abort()
        else:
            await self._context.__aexit__(None, None, None)

    async def _close(self) -> None:
        if not self.work.done():
            self.work.cancel()
        cleanup = asyncio.create_task(self._finish())
        try:
            # Shield so expiry can abort before waiting for cancellation to settle.
            await asyncio.wait_for(asyncio.shield(cleanup), self._cleanup_seconds)
        except (Exception, asyncio.CancelledError):
            self._abort()
            self.work.cancel()
            cleanup.cancel()
            await asyncio.gather(self.work, cleanup, return_exceptions=True)
        finally:
            self._connection = None

    async def close(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
        await await_cleanup(self._close_task)


class _QueryFailure(Exception):
    def __init__(self, category: ErrorCategory) -> None:
        self.category = category
        super().__init__(category.value)


def _message_id() -> str:
    return uuid4().hex


async def query_bindings(
    *,
    url: str,
    origin: str,
    principal: str,
    ticket: str,
    roles: str,
    cookie_header: str | None,
    notebook_id: str,
    max_response_bytes: int,
    max_opaque_id_chars: int,
    request_timeout_seconds: float,
    operation: ToolOperation,
    identifiers: Mapping[str, str],
    connector: SocketConnector = SingleQueryConnection,
    msg_id_factory: Callable[[], str] = _message_id,
    deadline: float | None = None,
) -> tuple[InterpreterBindingRecord, ...]:
    """Query using validated adapter-only auth; retain no session state.

    An optional absolute loop deadline includes the caller's HTTP and lock work.
    Cleanup has its own bounded allowance and never replaces a primary failure.
    """
    remaining = request_timeout_seconds if deadline is None else (
        deadline - asyncio.get_running_loop().time()
    )
    try:
        if remaining <= 0:
            raise asyncio.TimeoutError
        context = connector(
            url,
            origin=Origin(origin),
            additional_headers=None if cookie_header is None else {"Cookie": cookie_header},
            proxy=None,
            compression=None,
            max_queue=1,
            max_size=max_response_bytes,
            open_timeout=remaining,
            close_timeout=min(5.0, request_timeout_seconds),
            logger=_transport_logger,
        )
        query = _BindingQuery(
            context,
            payload=json.dumps(
                {
                    "op": "GET_INTERPRETER_BINDINGS",
                    "data": {"noteId": notebook_id},
                    "principal": principal,
                    "ticket": ticket,
                    "roles": roles,
                    "msgId": msg_id_factory(),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            max_response_bytes=max_response_bytes,
            max_opaque_id_chars=max_opaque_id_chars,
            cleanup_seconds=min(5.0, request_timeout_seconds),
        )
        try:
            return await asyncio.wait_for(asyncio.shield(query.work), remaining)
        finally:
            await query.close()
    except _QueryFailure as exc:
        category = exc.category
    except InvalidStatus as exc:
        category = {
            401: ErrorCategory.AUTHENTICATION_FAILED,
            403: ErrorCategory.PERMISSION_DENIED,
        }.get(exc.response.status_code, ErrorCategory.UPSTREAM_ERROR)
    except (TimeoutError, asyncio.TimeoutError):
        category = ErrorCategory.TIMEOUT
    except ConnectionClosed as exc:
        category = (
            ErrorCategory.UNEXPECTED_RESPONSE
            if exc.sent is not None and exc.sent.code == 1009
            else ErrorCategory.CONNECTION_FAILED
        )
    except (OSError, InvalidHandshake):
        category = ErrorCategory.CONNECTION_FAILED
    except (ValueError, TypeError, RecursionError):
        category = ErrorCategory.UNEXPECTED_RESPONSE
    raise ZeppelinGatewayError(ToolError.create(
        category=category,
        operation=operation,
        retryable=(operation == ToolOperation.GET_INTERPRETER_BINDINGS
                   and category in (ErrorCategory.TIMEOUT, ErrorCategory.CONNECTION_FAILED)),
        identifiers=safe_error_identifiers(operation, identifiers),
    )) from None


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("expected an object")
    return cast("dict[str, object]", value)


def _array(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("expected an array")
    return cast("list[object]", value)


def _reject_json_constant(value: str) -> None:
    raise ValueError("non-JSON numeric constant")


def _parse_bindings(
    data: dict[str, object], *, max_opaque_id_chars: int,
) -> tuple[InterpreterBindingRecord, ...]:
    items = _array(data.get("interpreterBindings"))
    if len(items) > _MAX_BINDINGS:
        raise ValueError("binding limit exceeded")
    records: list[InterpreterBindingRecord] = []
    setting_ids: set[str] = set()
    for item in items:
        binding = _object(item)
        record = InterpreterBindingRecord.model_validate({
            "setting_id": binding.get("id"),
            "name": binding.get("name"),
            "interpreters": tuple(
                _object(interpreter).get("name")
                for interpreter in _array(binding.get("interpreters"))
            ),
            "selected": binding.get("selected"),
        })
        validate_opaque_id(record.setting_id, max_chars=max_opaque_id_chars)
        if record.setting_id in setting_ids:
            raise ValueError("duplicate setting id")
        setting_ids.add(record.setting_id)
        records.append(record)
    return tuple(records)


async def _receive_bindings(
    connection: _Connection, *, max_response_bytes: int, max_opaque_id_chars: int,
) -> tuple[InterpreterBindingRecord, ...]:
    received_bytes = 0
    for _ in range(_MAX_MESSAGES):
        frame = await connection.recv()
        if not isinstance(frame, str):
            raise ValueError("binary messages are unsupported")
        received_bytes += len(frame.encode("utf-8"))
        if received_bytes > max_response_bytes:
            raise ValueError("response byte limit exceeded")
        envelope = _object(json.loads(frame, parse_constant=_reject_json_constant))
        op = envelope.get("op")
        if not isinstance(op, str):
            raise ValueError("invalid operation")
        if op in ("AUTH_INFO", "SESSION_LOGOUT"):
            raise _QueryFailure(ErrorCategory.AUTHENTICATION_FAILED)
        if op == "ERROR_INFO":
            raise _QueryFailure(ErrorCategory.UPSTREAM_ERROR)
        data = _object(envelope.get("data"))
        if op == "INTERPRETER_BINDINGS":
            return _parse_bindings(data, max_opaque_id_chars=max_opaque_id_chars)
    raise ValueError("message limit exceeded")
