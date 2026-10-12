"""Force-release seams for the adapter's owned HTTPX/asyncio network resources."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

import httpx


@runtime_checkable
class _NetworkStream(Protocol):
    def get_extra_info(self, info: str) -> object: ...


@runtime_checkable
class _SocketClose(Protocol):
    def close(self) -> None: ...


@runtime_checkable
class _SocketDescriptor(Protocol):
    def fileno(self) -> int: ...


@runtime_checkable
class _Abortable(Protocol):
    def abort(self) -> None: ...


@dataclass
class _Resource:
    socket: object
    abort: Callable[[], None]


def _network_resource(network: object) -> _Resource | None:
    if not isinstance(network, _NetworkStream):
        return None
    raw_socket = network.get_extra_info("socket")
    stream = getattr(network, "_stream", None)
    seen: set[int] = set()
    while stream is not None and id(stream) not in seen:
        seen.add(id(stream))
        # httpcore AnyIOStream -> AnyIO TLSStream(s) -> asyncio SocketStream.
        transport = getattr(stream, "_transport", None)
        if isinstance(transport, asyncio.Transport):
            return _Resource(raw_socket, transport.abort)
        stream = getattr(stream, "transport_stream", None)
    if isinstance(raw_socket, _SocketClose):
        return _Resource(raw_socket, raw_socket.close)
    return None


def abort_http_response(response: httpx.Response) -> None:
    resource = _network_resource(response.extensions.get("network_stream"))
    if resource is not None:
        resource.abort()


class _NetworkBackend(Protocol):
    async def connect_tcp(self, *args: Any, **kwargs: Any) -> object: ...
    async def connect_unix_socket(self, *args: Any, **kwargs: Any) -> object: ...
    async def sleep(self, seconds: float) -> None: ...


class _TrackingBackend:
    def __init__(self, backend: _NetworkBackend, record: Callable[[object], None]) -> None:
        self._backend = backend
        self._record = record

    async def connect_tcp(self, *args: Any, **kwargs: Any) -> object:
        stream = await self._backend.connect_tcp(*args, **kwargs)
        self._record(stream)
        return stream

    async def connect_unix_socket(self, *args: Any, **kwargs: Any) -> object:
        stream = await self._backend.connect_unix_socket(*args, **kwargs)
        self._record(stream)
        return stream

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class _Pool(Protocol):
    _network_backend: _NetworkBackend


class HttpResources:
    """Retain release handles before a connection can enter HTTP or TLS work."""

    def __init__(self) -> None:
        self._resources: dict[int, _Resource] = {}
        self._transport: httpx.AsyncBaseTransport | None = None

    def attach(self, transport: httpx.AsyncBaseTransport | None) -> httpx.AsyncBaseTransport:
        self._transport = transport if transport is not None else httpx.AsyncHTTPTransport(
            trust_env=False,
        )
        if isinstance(self._transport, httpx.AsyncHTTPTransport):
            # HTTPX doesn't expose httpcore's network_backend constructor argument.
            # Keep this version-sensitive seam together with its socket adapter.
            pool = cast(_Pool, self._transport._pool)  # pyright: ignore[reportPrivateUsage]
            pool._network_backend = _TrackingBackend(  # pyright: ignore[reportPrivateUsage]
                pool._network_backend, self.record,  # pyright: ignore[reportPrivateUsage]
            )
        return self._transport

    def record(self, network: object) -> None:
        self._resources = {
            key: item for key, item in self._resources.items()
            if not isinstance(item.socket, _SocketDescriptor) or item.socket.fileno() >= 0
        }
        resource = _network_resource(network)
        if resource is not None:
            self._resources[id(resource.socket)] = resource

    def abort(self) -> None:
        try:
            if isinstance(self._transport, _Abortable):
                self._transport.abort()
        finally:
            for resource in self._resources.values():
                try:
                    resource.abort()
                except Exception:
                    # A custom release hook must not skip the other owned sockets.
                    continue

    def clear(self) -> None:
        self._resources.clear()
