"""Private per-download directories and the Spark gateway implementation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import cast
from uuid import uuid4

import httpx
from pydantic import ValidationError

from mcp_stdio.core.config import ConfigError
from mcp_stdio.core.errors import ErrorCategory
from mcp_stdio.plugins.spark.config import SparkSecrets, SparkSettings
from mcp_stdio.plugins.spark.files import checkpoint, credential_values, process_archive
from mcp_stdio.plugins.spark.gateway import SparkGatewayError, spark_error
from mcp_stdio.plugins.spark.http_client import SparkHttpClient
from mcp_stdio.plugins.spark.models import FetchRequest, SparkEventLogFetchResult, SparkEventLogFile

_MANIFEST_BYTES = 131072


def _private_directory(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("unsafe directory")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir():
        raise ValueError("cache is not a directory")
    os.chmod(path, 0o700)


def _selector(root: Path, application_id: str, attempt_id: str | None) -> Path:
    path = root / application_id / ("all" if attempt_id is None else f"attempt-{attempt_id}")
    if any(parent.is_symlink() for parent in (root, path.parent, path)):
        raise ValueError("unsafe cache path")
    return path


def _open_private(path: Path) -> int:
    return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)


def _read_manifest(path: Path) -> dict[str, object]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("manifest is not a regular file")
        raw = stream.read(_MANIFEST_BYTES + 1)
    if len(raw) > _MANIFEST_BYTES:
        raise ValueError("manifest is too large")
    value = cast(object, json.loads(raw))
    if not isinstance(value, dict):
        raise ValueError("invalid manifest")
    return cast(dict[str, object], value)


def _write_manifest(
    path: Path, result: SparkEventLogFetchResult, source: str, secrets: tuple[str, ...]
) -> None:
    body = {
        "format_version": 1,
        "history_server_url": source,
        **result.model_dump(mode="json", exclude={"cache_hit"}),
    }
    raw = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if any(secret in raw for secret in secrets) or len(raw.encode()) > _MANIFEST_BYTES:
        raise ValueError("unsafe manifest")
    with os.fdopen(_open_private(path), "wb") as output:
        output.write(raw.encode("utf-8"))


def _candidate_directories(selector: Path) -> list[Path]:
    if not selector.exists():
        return []
    return [path for path in selector.iterdir() if re.fullmatch(r"[0-9a-f]{32}", path.name)]


class SparkEventLogAdapter:
    def __init__(
        self,
        *,
        settings: SparkSettings,
        secrets: SparkSecrets,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._root = Path(settings.cache_dir)
        self._lock_fd: int | None = None
        self._closed = False
        self._download_lock = asyncio.Lock()
        cookie = secrets.gateway_cookie
        self._secret_values = credential_values(
            (cookie.get_secret_value(),) if cookie is not None else ()
        )
        try:
            if os.name != "posix":
                raise ValueError("POSIX required")
            import fcntl

            _private_directory(self._root)
            self._root = self._root.resolve()
            fd = os.open(self._root / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise ValueError("unsafe cache lock")
                os.fchmod(fd, 0o600)
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BaseException:
                os.close(fd)
                raise
            self._lock_fd = fd
        except (OSError, ValueError, ImportError):
            raise ConfigError("Spark cache directory is unavailable or already in use") from None
        self._http = SparkHttpClient(settings=settings, secrets=secrets, transport=transport)

    async def lookup(
        self, application_id: str, attempt_id: str | None, *, deadline: float
    ) -> SparkEventLogFetchResult | None:
        FetchRequest(application_id=application_id, attempt_id=attempt_id)
        if self._closed:
            raise spark_error(ErrorCategory.UPSTREAM_ERROR)
        try:
            candidates: list[SparkEventLogFetchResult] = []
            selector = _selector(self._root, application_id, attempt_id)
            for directory in _candidate_directories(selector):
                await checkpoint(deadline)
                if directory.is_symlink() or not directory.is_dir():
                    raise ValueError("unsafe cache candidate")
                manifest = _read_manifest(directory / "manifest.json")
                if manifest.get("history_server_url") != self._settings.history_server_url:
                    if "history_server_url" not in manifest:
                        raise ValueError("corrupt manifest")
                    continue
                if manifest.pop("format_version", None) != 1:
                    raise ValueError("unsupported manifest format")
                manifest.pop("history_server_url")
                result = SparkEventLogFetchResult.model_validate_json(
                    json.dumps(
                        {
                            **manifest,
                            "cache_hit": True,
                        }
                    )
                )
                if (
                    result.application_id != application_id
                    or result.requested_attempt_id != attempt_id
                ):
                    continue
                if Path(result.manifest_path) != directory / "manifest.json":
                    raise ValueError("manifest path mismatch")
                candidates.append(result)
            if not candidates:
                return None
            result = max(candidates, key=lambda item: (item.downloaded_at, item.manifest_path))
            directory = Path(result.manifest_path).parent
            total = 0
            for file in result.files:
                await checkpoint(deadline)
                path = Path(file.local_path)
                if path.parent != directory or not re.fullmatch(
                    r"eventlog-[0-9]{4}\.jsonl", path.name
                ):
                    raise ValueError("unsafe cached file")
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size != file.size_bytes:
                        raise ValueError("cached file size mismatch")
                    digest = hashlib.sha256()
                    while chunk := stream.read(65536):
                        total += len(chunk)
                        if total > self._settings.max_bytes:
                            raise ValueError("cached files exceed limits")
                        digest.update(chunk)
                        await checkpoint(deadline)
                if digest.hexdigest() != file.sha256:
                    raise ValueError("cached file digest mismatch")
            if any(secret in result.model_dump_json() for secret in self._secret_values):
                raise ValueError("unsafe cached metadata")
            return result
        except SparkGatewayError:
            raise
        except (OSError, ValueError, ValidationError):
            raise spark_error(
                ErrorCategory.UNEXPECTED_RESPONSE,
                application_id=application_id,
                attempt_id=attempt_id,
            ) from None

    async def download(
        self, application_id: str, attempt_id: str | None, *, deadline: float
    ) -> SparkEventLogFetchResult:
        FetchRequest(application_id=application_id, attempt_id=attempt_id)
        if self._closed:
            raise spark_error(ErrorCategory.UPSTREAM_ERROR)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise spark_error(ErrorCategory.TIMEOUT, retryable=True)
        try:
            return await asyncio.wait_for(
                self._download(application_id, attempt_id, deadline), timeout=remaining
            )
        except asyncio.TimeoutError:
            raise spark_error(ErrorCategory.TIMEOUT, retryable=True) from None
        except PermissionError:
            raise spark_error(ErrorCategory.PERMISSION_DENIED) from None
        except OSError:
            raise spark_error(ErrorCategory.UPSTREAM_ERROR) from None
        except (ValueError, ValidationError):
            raise spark_error(ErrorCategory.UNEXPECTED_RESPONSE) from None

    async def _download(
        self, application_id: str, attempt_id: str | None, deadline: float
    ) -> SparkEventLogFetchResult:
        async with self._download_lock:
            await checkpoint(deadline)
            selector = _selector(self._root, application_id, attempt_id)
            _private_directory(selector.parent)
            _private_directory(selector)
            final = selector / uuid4().hex
            staging = Path(tempfile.mkdtemp(prefix=".part-", dir=self._root))
            try:
                archive = staging / "archive.zip"
                await self._http.receive(application_id, attempt_id, archive, deadline=deadline)
                files = await process_archive(
                    archive,
                    staging,
                    application_id=application_id,
                    attempt_id=attempt_id,
                    max_bytes=self._settings.max_bytes,
                    deadline=deadline,
                    secret_values=self._secret_values,
                )
                result = SparkEventLogFetchResult(
                    application_id=application_id,
                    requested_attempt_id=attempt_id,
                    cache_hit=False,
                    downloaded_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    manifest_path=str(final / "manifest.json"),
                    files=tuple(
                        SparkEventLogFile.model_validate(
                            {
                                **file.model_dump(),
                                "local_path": str(final / Path(file.local_path).name),
                            }
                        )
                        for file in files
                    ),
                )
                await checkpoint(deadline)
                _write_manifest(
                    staging / "manifest.json",
                    result,
                    self._settings.history_server_url,
                    self._secret_values,
                )
                os.unlink(archive)
                os.rename(staging, final)
                return result
            finally:
                shutil.rmtree(staging, ignore_errors=True)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._http.close()
        finally:
            if self._lock_fd is not None:
                os.close(self._lock_fd)
                self._lock_fd = None
