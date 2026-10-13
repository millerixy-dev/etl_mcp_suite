"""One-pass validation of explicitly selected, private local Spark evidence."""

# ruff: noqa: ASYNC240 -- cooperative bounded local reads; no upstream I/O
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, cast

from pydantic import ValidationError

from mcp_stdio.core.errors import ErrorCategory
from mcp_stdio.plugins.spark.config import SparkSettings
from mcp_stdio.plugins.spark.files import (
    MAX_LINE_BYTES,
    checkpoint,
    credential_values,
)
from mcp_stdio.plugins.spark.gateway import SparkGatewayError, spark_error
from mcp_stdio.plugins.spark.inspection_models import (
    InspectRequest,
    QueryRequest,
    SparkEventCoverage,
    SparkSnapshot,
)
from mcp_stdio.plugins.spark.models import SparkEventLogFetchResult

MAX_MANIFEST_BYTES = 131072


@dataclass(frozen=True)
class VerifiedScan:
    snapshot: SparkSnapshot
    spark_version: str
    event_count: int
    coverage: SparkEventCoverage


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite JSON number")
    return number


def _private(fd: int, *, directory: bool) -> os.stat_result:
    info = os.fstat(fd)
    if (
        not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
        or info.st_mode & 0o077
        or info.st_uid != os.getuid()
    ):
        raise ValueError("unsafe private evidence")
    return info


def _stream(stack: ExitStack, directory: int, name: str) -> BinaryIO:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        _private(fd, directory=False)
        stream = os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise
    return stack.enter_context(stream)


class VerifiedEventLogReader:
    def __init__(self, settings: SparkSettings, secret_values: tuple[str, ...] = ()) -> None:
        self._settings = settings
        self._secrets = credential_values(secret_values)

    async def read(
        self,
        request: InspectRequest,
        visitor: Callable[[int, dict[str, object]], None],
        *,
        deadline: float,
    ) -> VerifiedScan:
        try:
            await checkpoint(deadline)
            configured_root = Path(self._settings.cache_dir)
            if configured_root.is_symlink():
                raise ValueError("unsafe cache root")
            root = configured_root.resolve()
            manifest_path = Path(request.manifest_path)
            if manifest_path.is_relative_to(configured_root):
                manifest_path = root / manifest_path.relative_to(configured_root)
            # Lexical containment precedes descriptor traversal; configured ancestors
            # may be OS aliases, but root and every descendant must be real directories.
            relative = manifest_path.relative_to(root)
            if ".." in relative.parts or relative.name != "manifest.json":
                raise ValueError("unsafe manifest path")
            with ExitStack() as stack:
                directory = os.open(configured_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                stack.callback(os.close, directory)
                _private(directory, directory=True)
                for part in relative.parts[:-1]:
                    directory = os.open(
                        part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
                    )
                    stack.callback(os.close, directory)
                    _private(directory, directory=True)
                manifest_stream = _stream(stack, directory, relative.name)
                raw_manifest = manifest_stream.read(MAX_MANIFEST_BYTES + 1)
                if len(raw_manifest) > MAX_MANIFEST_BYTES:
                    raise ValueError("manifest limit")
                parsed = cast(
                    object,
                    json.loads(
                        raw_manifest, parse_constant=_finite_float, parse_float=_finite_float
                    ),
                )
                if not isinstance(parsed, dict):
                    raise ValueError("manifest object required")
                manifest = cast(dict[str, object], parsed)
                if (
                    type(manifest.get("format_version")) is not int
                    or manifest.pop("format_version") != 1
                    or manifest.pop("history_server_url", None) != self._settings.history_server_url
                    or "cache_hit" in manifest
                ):
                    raise ValueError("manifest source or format")
                result = SparkEventLogFetchResult.model_validate_json(
                    json.dumps({**manifest, "cache_hit": True}, allow_nan=False)
                )
                if result.manifest_path != str(manifest_path):
                    raise ValueError("manifest path mismatch")
                if any(secret in result.model_dump_json() for secret in self._secrets):
                    raise ValueError("unsafe metadata")
                selected = next(
                    (file for file in result.files if file.attempt_id == request.attempt_id), None
                )
                if selected is None:
                    raise spark_error(ErrorCategory.NOT_FOUND)
                path = Path(selected.local_path)
                if path.parent != manifest_path.parent or not re.fullmatch(
                    r"eventlog-[0-9]{4}\.jsonl", path.name
                ):
                    raise ValueError("unsafe event path")
                if isinstance(request, QueryRequest) and request.expected_sha256 != selected.sha256:
                    raise ValueError("snapshot conflict")
                stream = _stream(stack, directory, path.name)
                before = os.fstat(stream.fileno())
                if before.st_size != selected.size_bytes:
                    raise ValueError("file size mismatch")
                if before.st_size > self._settings.max_bytes:
                    raise ValueError("event log exceeds byte limits")
                digest = hashlib.sha256()
                count = size = 0
                version: str | None = None
                start = end = False
                while True:
                    await checkpoint(deadline)
                    raw = stream.readline(MAX_LINE_BYTES + 1)
                    if not raw:
                        break
                    size += len(raw)
                    count += 1
                    if (
                        size > self._settings.max_bytes
                        or len(raw) > MAX_LINE_BYTES
                        or count > selected.event_count
                    ):
                        raise ValueError("event log exceeds limits")
                    digest.update(raw)
                    parsed = cast(
                        object,
                        json.loads(
                            raw.decode("utf-8"),
                            parse_constant=_finite_float,
                            parse_float=_finite_float,
                        ),
                    )
                    if not isinstance(parsed, dict):
                        raise ValueError("invalid event object")
                    event = cast(dict[str, object], parsed)
                    name = event.get("Event")
                    if (
                        not isinstance(name, str)
                        or not 1 <= len(name) <= 512
                        or any(ord(c) < 32 or ord(c) == 127 for c in name)
                    ):
                        raise ValueError("invalid event name")
                    if name == "SparkListenerLogStart":
                        observed = event.get("Spark Version")
                        if observed != selected.spark_version:
                            raise ValueError("Spark version mismatch")
                        version = selected.spark_version
                    elif name == "SparkListenerApplicationStart":
                        if (
                            event.get("App ID") != result.application_id
                            or event.get("App Attempt ID") != selected.attempt_id
                        ):
                            raise ValueError("application identity mismatch")
                        start = True
                    end |= name == "SparkListenerApplicationEnd"
                    visitor(count, event)
                after = os.fstat(stream.fileno())
                if (
                    size != selected.size_bytes
                    or count != selected.event_count
                    or digest.hexdigest() != selected.sha256
                    or not start
                    or version is None
                    or end != selected.application_end_seen
                    or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                ):
                    raise ValueError("snapshot metadata mismatch")
                return VerifiedScan(
                    snapshot=SparkSnapshot(
                        application_id=result.application_id,
                        attempt_id=selected.attempt_id,
                        sha256=selected.sha256,
                    ),
                    spark_version=version,
                    event_count=count,
                    coverage=SparkEventCoverage(
                        application_start_seen=start, application_end_seen=end
                    ),
                )
        except SparkGatewayError:
            raise
        except FileNotFoundError:
            raise spark_error(ErrorCategory.NOT_FOUND) from None
        except (OSError, ValueError, UnicodeError, ValidationError):
            raise spark_error(ErrorCategory.UNEXPECTED_RESPONSE) from None
