"""Gateway-only container logs resolved from verified Spark event evidence."""

from __future__ import annotations

import re
import ssl
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import NoReturn, cast
from urllib.parse import SplitResult, parse_qsl, quote, unquote, urlencode, urljoin, urlsplit

import httpx

from mcp_stdio.core.errors import ErrorCategory
from mcp_stdio.plugins.spark.config import SparkSecrets, SparkSettings
from mcp_stdio.plugins.spark.executor_log_models import SparkExecutorLogRequest
from mcp_stdio.plugins.spark.files import checkpoint, credential_values, redact_event
from mcp_stdio.plugins.spark.gateway import SparkEventLogGateway, spark_error
from mcp_stdio.plugins.spark.http_client import SparkHttpClient
from mcp_stdio.plugins.spark.inspection_models import InspectRequest
from mcp_stdio.plugins.spark.inspection_reader import VerifiedEventLogReader
from mcp_stdio.plugins.spark.models import SparkEventLogFile

_RESPONSE_LIMIT = 8 * 1024 * 1024
_OUTPUT_LIMIT = 1024 * 1024
_CONTAINER = re.compile(r"container_(?:e[0-9]+_)?([0-9]+)_([0-9]+)_([0-9]+)_[0-9]+")


def _invalid() -> NoReturn:
    raise spark_error(ErrorCategory.UNEXPECTED_RESPONSE)


def _parts(url: str) -> SplitResult:
    if len(url) > 8192 or any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url:
        _invalid()
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        _invalid()
    _ = parsed.port
    return parsed


def _segments(path: str) -> list[str]:
    parts = path.split("/")
    for index, part in enumerate(parts):
        decoded = unquote(part, errors="strict")
        if (
            decoded in {".", ".."}
            or any(c in decoded for c in "/\\%")
            or any(ord(c) < 32 or ord(c) == 127 for c in decoded)
        ):
            _invalid()
        parts[index] = decoded
    return parts


class _LogRoute:
    """Pin identity and embedded backend before every credentialed gateway GET."""

    def __init__(
        self, settings: SparkSettings, request: SparkExecutorLogRequest, original: str
    ) -> None:
        self.settings, self.request = settings, request
        self.root = settings.history_server_url.removesuffix("/sparkhistory")
        self.nm_path = urlsplit(self.root).path + cast(str, settings.executor_log_node_manager_path)
        self.jhs_path = urlsplit(self.root).path + "/jobhistory/joblogs"
        self.history_backend: tuple[str, str, int] | None = None
        parsed = _parts(original)
        path = _segments(parsed.path)
        if parsed.netloc == urlsplit(self.root).netloc and parsed.scheme == "https":
            if parsed.path.startswith(self.nm_path + "/containerlogs/"):
                self.container, self.owner, stream = self._identity(path[-3:])
                self.node_backend = self._backend(self._query(parsed.query, gateway=True))
            elif parsed.path.startswith(self.jhs_path + "/"):
                if len(path) != len(_segments(self.jhs_path)) + 5:
                    _invalid()
                self.container, self.owner, stream = self._identity(path[-4:-3] + path[-2:])
                self.node_backend = ("http", self._node_id(path[-5])[0], 0)
            else:
                _invalid()
        else:
            if len(path) != 6 or path[:3] != ["", "node", "containerlogs"]:
                _invalid()
            self.container, self.owner, stream = self._identity(path[-3:])
            self.node_backend = (
                parsed.scheme,
                parsed.hostname or "",
                parsed.port or (443 if parsed.scheme == "https" else 80),
            )
            self._allowed(self.node_backend)
            self._query(parsed.query, gateway=False)
        if stream != request.log_type:
            _invalid()
        if self.node_backend[2] == 0:
            self.url = self._gateway(original)
        else:
            path = (
                self.nm_path
                + "/containerlogs/"
                + "/".join(
                    quote(p, safe="") for p in (self.container, self.owner, request.log_type)
                )
            )
            self.url = self.root_origin + path + "?" + self._params(self.node_backend)
            if parsed.netloc == urlsplit(self.root).netloc and parsed.scheme == "https":
                self.url = self._gateway(original)

    @property
    def root_origin(self) -> str:
        p = urlsplit(self.root)
        return f"{p.scheme}://{p.netloc}"

    def _identity(self, parts: list[str]) -> tuple[str, str, str]:
        if len(parts) != 3:
            _invalid()
        container, owner, stream = parts
        match = _CONTAINER.fullmatch(container)
        app_parts = self.request.application_id.split("_")[1:]
        if (
            len(container) > 256
            or match is None
            or tuple(map(int, match.groups()[:2])) != tuple(map(int, app_parts))
            or int(match.group(3)) != int(self.request.attempt_id)
        ):
            _invalid()
        if not 1 <= len(owner) <= 256 or owner in {".", ".."} or stream != self.request.log_type:
            _invalid()
        return container, owner, stream

    def _query(self, query: str, *, gateway: bool) -> dict[str, str]:
        pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=True)
        allowed = {"start", "scheme", "host", "port"} if gateway else {"start"}
        if len({k for k, _ in pairs}) != len(pairs) or any(k not in allowed for k, _ in pairs):
            _invalid()
        values = dict(pairs)
        if "start" in values and not re.fullmatch(r"-?[0-9]{1,20}", values["start"]):
            _invalid()
        return values

    def _backend(self, values: dict[str, str]) -> tuple[str, str, int]:
        if not {"scheme", "host", "port"} <= values.keys() or not re.fullmatch(
            r"[0-9]{1,5}", values["port"]
        ):
            _invalid()
        backend = (values["scheme"], values["host"], int(values["port"]))
        self._allowed(backend)
        return backend

    def _allowed(self, backend: tuple[str, str, int]) -> None:
        scheme, host, port = backend
        if not 1 <= port <= 65535 or host != host.lower():
            _invalid()
        for rule in self.settings.executor_log_allowed_upstreams:
            p = urlsplit(rule)
            pattern = re.escape(p.hostname or "").replace(r"\*", "[a-z0-9-]+")
            if scheme == p.scheme and port == p.port and re.fullmatch(pattern, host):
                return
        _invalid()

    def _node_id(self, value: str) -> tuple[str, int]:
        host, sep, port = value.rpartition(":")
        if (
            not sep
            or not re.fullmatch(r"[a-z0-9.-]+", host)
            or not re.fullmatch(r"[0-9]{1,5}", port)
            or not 1 <= int(port) <= 65535
        ):
            _invalid()
        return host, int(port)

    def _params(self, backend: tuple[str, str, int]) -> str:
        return urlencode(
            dict(
                start=-self.request.tail_bytes, scheme=backend[0], host=backend[1], port=backend[2]
            )
        )

    def _gateway(self, url: str) -> str:
        p = _parts(url)
        if (p.scheme, p.netloc) != ("https", urlsplit(self.root).netloc):
            _invalid()
        path = _segments(p.path)
        backend = self._backend(self._query(p.query, gateway=True))
        if p.path.startswith(self.nm_path + "/containerlogs/"):
            if len(path) != len(_segments(self.nm_path)) + 4 or backend != self.node_backend:
                _invalid()
            identity = self._identity(path[-3:])
        elif p.path.startswith(self.jhs_path + "/"):
            if len(path) != len(_segments(self.jhs_path)) + 5:
                _invalid()
            if path[-3] != self.container or self._node_id(path[-5])[0] != self.node_backend[1]:
                _invalid()
            identity = self._identity(path[-4:-3] + path[-2:])
            if self.history_backend is not None and self.history_backend != backend:
                _invalid()
            self.history_backend = backend
        else:
            _invalid()
        if identity != (self.container, self.owner, self.request.log_type):
            _invalid()
        return (
            self.root_origin
            + "/".join(quote(s, safe=":" if i == len(path) - 5 else "") for i, s in enumerate(path))
            + "?"
            + self._params(backend)
        )

    def redirect(self, current: str, location: str) -> str:
        target = urljoin(current, location)
        if re.search(r"(?:login|knoxsso|websso|/sso)(?:[/?#]|$)", urlsplit(target).path, re.I):
            raise spark_error(ErrorCategory.AUTHENTICATION_FAILED)
        return self._gateway(target)


@dataclass(frozen=True)
class _LogContent:
    text: str
    source_size: int | None
    coverage: str
    source_url: str = ""
    secret_values: tuple[str, ...] = ()
    start_discarded: bool = False
    output_trimmed: bool = False


class _LogHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.outside: list[str] = []
        self.blocks: list[tuple[str, str]] = []
        self.content: list[str] | None = None
        self.context = ""
        self.login = False
        self.unsafe = False
        self.ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "form" or (tag == "input" and values.get("type", "").lower() == "password"):
            self.login = True
        if tag in {"script", "style"}:
            self.ignored += 1
        if tag == "meta" and (
            values.get("charset", "utf-8").lower() not in {"utf-8", "utf8"}
            or "charset=" in values.get("content", "").lower()
            and not re.search(r"charset=utf-?8", values.get("content", ""), re.I)
        ):
            self.unsafe = True
        if tag == "pre":
            if self.content is not None:
                self.unsafe = True
            self.context = " ".join(self.outside)
            self.outside.clear()
            self.content = []
        elif self.content is None:
            self.outside.append(" ")
        else:
            self.unsafe = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.ignored = max(0, self.ignored - 1)
        if tag == "pre":
            if self.content is None:
                self.unsafe = True
            else:
                self.blocks.append((self.context, "".join(self.content)))
                self.content = None
        elif self.content is None:
            self.outside.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            (self.outside if self.content is None else self.content).append(data)


def parse_log_html(raw: bytes, stream: str, container: str) -> _LogContent:
    try:
        parser = _LogHTML()
        parser.feed(raw.decode("utf-8", errors="strict"))
        parser.close()
        outside = " ".join([context for context, _ in parser.blocks] + parser.outside)
        if parser.login:
            raise spark_error(ErrorCategory.AUTHENTICATION_FAILED)
        lower = outside.lower()
        if any(
            s in lower
            for s in (
                "not authorized",
                "authorization failed",
                "access denied",
                "permission denied",
                "not have permission",
            )
        ):
            raise spark_error(ErrorCategory.PERMISSION_DENIED)
        if any(
            s in lower
            for s in (
                "logs not available",
                "logs are not available",
                "cannot find",
                "aggregation is not complete",
                "aggregation has not completed",
                "log aggregation has not completed",
                "no logs available",
            )
        ):
            raise spark_error(ErrorCategory.NOT_FOUND, retryable="not complete" in lower)
        if parser.unsafe or parser.content is not None:
            _invalid()
        identities = re.findall(r"container_(?:e[0-9]+_)?[0-9]+_[0-9]+_[0-9]+_[0-9]+", outside)
        if any(value != container for value in identities):
            _invalid()
        candidates: list[tuple[str, str]] = []
        for context, text in parser.blocks:
            types = re.findall(r"Log Type\s*:\s*(\w+)", context, re.I)
            if types == [stream]:
                candidates.append((context, text))
            elif types or text.strip():
                _invalid()
        if len(candidates) != 1:
            _invalid()
        context, text = candidates[0]
        lengths = re.findall(r"Log Length\s*:\s*([0-9]+)", context, re.I)
        if len(lengths) > 1:
            _invalid()
        total = int(lengths[0]) if lengths else None
        size = len(text.encode("utf-8"))
        if total is not None and size > total:
            _invalid()
        coverage = "unknown" if total is None else ("complete" if size == total else "tail")
        return _LogContent(text, total, coverage)
    except (ValueError, UnicodeError):
        raise spark_error(ErrorCategory.UNEXPECTED_RESPONSE) from None


class SparkExecutorLogAdapter:
    def __init__(
        self,
        *,
        settings: SparkSettings,
        secrets: SparkSecrets,
        event_logs: SparkEventLogGateway,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings, self._secrets, self._event_logs = settings, secrets, event_logs
        self._transport = transport
        self._reader = VerifiedEventLogReader(settings, secrets.redaction_values)
        self._closed = False

    async def _resolve(
        self, request: SparkExecutorLogRequest, *, deadline: float
    ) -> tuple[_LogRoute, SparkEventLogFile]:
        evidence = await self._event_logs.lookup(
            request.application_id, request.attempt_id, deadline=deadline
        )
        if evidence is None:
            evidence = await self._event_logs.download(
                request.application_id, request.attempt_id, deadline=deadline
            )
        selected: list[object] = [None]

        def visit(line: int, event: dict[str, object]) -> None:
            if (
                request.executor_id == "driver"
                and event.get("Event") == "SparkListenerApplicationStart"
            ):
                selected[0] = event.get("Driver Logs")
            elif (
                event.get("Event") == "SparkListenerExecutorAdded"
                and event.get("Executor ID") == request.executor_id
            ):
                info = event.get("Executor Info")
                selected[0] = (
                    cast(dict[str, object], info).get("Log Urls")
                    if isinstance(info, dict)
                    else None
                )

        scan = await self._reader.read(
            InspectRequest(manifest_path=evidence.manifest_path, attempt_id=request.attempt_id),
            visit,
            deadline=deadline,
        )
        if (
            scan.snapshot.application_id != request.application_id
            or scan.snapshot.attempt_id != request.attempt_id
        ):
            _invalid()
        urls = cast(dict[str, object], selected[0]) if isinstance(selected[0], dict) else {}
        original = urls.get(request.log_type)
        if original is None:
            raise spark_error(
                ErrorCategory.NOT_FOUND,
                explanation="Executor or stream is absent; explicitly refresh eventlog evidence.",
            )
        if not isinstance(original, str):
            _invalid()
        file = next(f for f in evidence.files if f.attempt_id == request.attempt_id)
        return _LogRoute(self._settings, request, original), file

    async def _receive(self, route: _LogRoute, *, deadline: float) -> _LogContent:
        auth = SparkHttpClient(
            settings=self._settings, secrets=self._secrets, transport=self._transport
        )
        values = self._secrets.redaction_values
        url = route.url
        seen: set[str] = set()
        total = 0
        try:
            async with auth.authenticated(url, deadline=deadline) as client:
                for step in range(4):
                    await checkpoint(deadline)
                    if url in seen:
                        _invalid()
                    seen.add(url)
                    headers = {"Accept-Encoding": "identity"}
                    if self._secrets.gateway_cookie is not None:
                        headers["Cookie"] = self._secrets.gateway_cookie.get_secret_value()
                    async with client.stream(
                        "GET", url, headers=headers, timeout=max(0.001, deadline - time.monotonic())
                    ) as response:
                        values += tuple(c.value for c in client.cookies.jar if c.value)
                        status = response.status_code
                        if (
                            response.headers.get("content-encoding", "identity").lower()
                            != "identity"
                        ):
                            _invalid()
                        body = bytearray()
                        async for chunk in response.aiter_bytes(chunk_size=65536):
                            total += len(chunk)
                            if total > _RESPONSE_LIMIT:
                                raise spark_error(ErrorCategory.UPSTREAM_ERROR)
                            body.extend(chunk)
                            await checkpoint(deadline)
                        if status in {302, 303, 307, 308}:
                            if step == 3 or not response.headers.get("location"):
                                _invalid()
                            url = route.redirect(url, response.headers["location"])
                            continue
                        if status != 200:
                            category = {
                                401: ErrorCategory.AUTHENTICATION_FAILED,
                                403: ErrorCategory.PERMISSION_DENIED,
                                404: ErrorCategory.NOT_FOUND,
                            }.get(status, ErrorCategory.UPSTREAM_ERROR)
                            raise spark_error(category, retryable=status == 429 or status >= 500)
                        if (
                            response.headers.get("content-encoding", "identity").lower()
                            != "identity"
                        ):
                            _invalid()
                        content_type = (
                            response.headers.get("content-type", "").lower().replace(" ", "")
                        )
                        if "charset=" in content_type and not re.search(
                            r"charset=\"?utf-?8(?:\"|;|$)", content_type
                        ):
                            _invalid()
                        parsed = parse_log_html(
                            bytes(body), route.request.log_type, route.container
                        )
                        values = credential_values(values)
                        redacted = cast(
                            dict[str, object],
                            redact_event({"Event": "DiagnosticText", "text": parsed.text}, values),
                        )["text"]
                        await checkpoint(deadline)
                        return _LogContent(
                            cast(str, redacted), parsed.source_size, parsed.coverage, url, values
                        )
        except httpx.TimeoutException:
            raise spark_error(ErrorCategory.TIMEOUT, retryable=True) from None
        except httpx.TransportError as error:
            tls = isinstance(error.__cause__, ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in str(
                error
            )
            raise spark_error(ErrorCategory.CONNECTION_FAILED, retryable=not tls) from None
        except (ValueError, UnicodeError):
            raise spark_error(ErrorCategory.UNEXPECTED_RESPONSE) from None
        finally:
            await auth.close()
        raise spark_error(ErrorCategory.UNEXPECTED_RESPONSE)

    async def close(self) -> None:
        self._closed = True
