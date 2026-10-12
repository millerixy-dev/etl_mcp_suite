"""Standard-library ZIP validation and private JSONL generation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import stat
import time
import zipfile
from pathlib import Path
from typing import NoReturn, cast

from mcp_stdio.core.errors import ErrorCategory
from mcp_stdio.plugins.spark.gateway import spark_error
from mcp_stdio.plugins.spark.models import (
    FetchRequest,
    SparkEventLogFile,
    validate_application_id,
    validate_attempt_id,
)

MAX_MEMBERS = 16
MAX_LINE_BYTES = 8 * 1024 * 1024


async def checkpoint(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise spark_error(ErrorCategory.TIMEOUT, retryable=True)
    await asyncio.sleep(0)


def _reject() -> NoReturn:
    raise spark_error(ErrorCategory.UNEXPECTED_RESPONSE)


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


def _member_safe(member: zipfile.ZipInfo) -> None:
    kind = stat.S_IFMT(member.external_attr >> 16)
    if (
        not member.filename
        or len(member.filename) > 512
        or "/" in member.filename
        or "\\" in member.filename
        or member.filename in {".", ".."}
        or member.is_dir()
        or kind not in {0, stat.S_IFREG}
        or member.flag_bits & 1
        or member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
    ):
        _reject()


async def process_archive(
    archive: Path,
    directory: Path,
    *,
    application_id: str,
    attempt_id: str | None,
    max_bytes: int,
    deadline: float,
    secret_values: tuple[str, ...] = (),
) -> tuple[SparkEventLogFile, ...]:
    FetchRequest(application_id=application_id, attempt_id=attempt_id)
    files: list[SparkEventLogFile] = []
    total_source = 0
    total_output = 0
    attempts: set[str | None] = set()
    try:
        await checkpoint(deadline)
        with zipfile.ZipFile(archive) as source:
            members = source.infolist()
            if not 1 <= len(members) <= MAX_MEMBERS:
                _reject()
            names = [member.filename for member in members]
            if len(names) != len(set(names)):
                _reject()
            for index, member in enumerate(members, start=1):
                _member_safe(member)
                version: str | None = None
                identity: tuple[str, str | None] | None = None
                end_seen = False
                count = 0
                size = 0
                source_hash = hashlib.sha256()
                output_hash = hashlib.sha256()
                destination = directory / f"eventlog-{index:04d}.jsonl"
                fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "wb") as output, source.open(member) as stream:
                    while True:
                        await checkpoint(deadline)
                        raw = stream.readline(MAX_LINE_BYTES + 1)
                        if not raw:
                            break
                        total_source += len(raw)
                        if total_source > max_bytes or len(raw) > MAX_LINE_BYTES:
                            raise spark_error(
                                ErrorCategory.UPSTREAM_ERROR,
                                explanation="Event log exceeds byte limits.",
                            )
                        source_hash.update(raw)
                        parsed = cast(
                            object, json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
                        )
                        if not isinstance(parsed, dict):
                            _reject()
                        event = cast(dict[str, object], parsed)
                        name = event.get("Event")
                        if (
                            not isinstance(name, str)
                            or not name
                            or len(name) > 512
                            or any(ord(c) < 32 or ord(c) == 127 for c in name)
                        ):
                            _reject()
                        if name == "SparkListenerLogStart":
                            observed = event.get("Spark Version")
                            if (
                                not isinstance(observed, str)
                                or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", observed)
                                or version is not None
                                and version != observed
                            ):
                                _reject()
                            version = observed
                        if name == "SparkListenerApplicationStart":
                            app = event.get("App ID")
                            attempt = event.get("App Attempt ID")
                            if not isinstance(app, str) or (
                                attempt is not None and not isinstance(attempt, str)
                            ):
                                _reject()
                            observed_identity = (
                                validate_application_id(app),
                                validate_attempt_id(attempt),
                            )
                            if observed_identity[0] != application_id or (
                                attempt_id is not None and observed_identity[1] != attempt_id
                            ):
                                _reject()
                            if identity is not None and identity != observed_identity:
                                _reject()
                            identity = observed_identity
                        end_seen |= name == "SparkListenerApplicationEnd"
                        encoded = (
                            json.dumps(
                                event, ensure_ascii=False, allow_nan=False, separators=(",", ":")
                            )
                            + "\n"
                        ).encode("utf-8")
                        total_output += len(encoded)
                        if total_output > max_bytes or len(encoded) > MAX_LINE_BYTES:
                            raise spark_error(ErrorCategory.UPSTREAM_ERROR)
                        output.write(encoded)
                        output_hash.update(encoded)
                        size += len(encoded)
                        count += 1
                if identity is None or version is None or identity[1] in attempts:
                    _reject()
                expected = application_id + (f"_{identity[1]}" if identity[1] is not None else "")
                if member.filename not in {expected, expected + ".inprogress"}:
                    _reject()
                attempts.add(identity[1])
                files.append(
                    SparkEventLogFile(
                        attempt_id=identity[1],
                        local_path=str(destination),
                        spark_version=version,
                        size_bytes=size,
                        sha256=output_hash.hexdigest(),
                        source_sha256=source_hash.hexdigest(),
                        event_count=count,
                        application_end_seen=end_seen,
                    )
                )
        if attempt_id is not None and len(files) != 1:
            _reject()
        return tuple(
            sorted(files, key=lambda item: (item.attempt_id is not None, item.attempt_id or ""))
        )
    except (zipfile.BadZipFile, ValueError, UnicodeError, NotImplementedError, RuntimeError) as exc:
        from mcp_stdio.plugins.spark.gateway import SparkGatewayError

        if isinstance(exc, SparkGatewayError):
            raise
        raise spark_error(ErrorCategory.UNEXPECTED_RESPONSE) from None
    except PermissionError:
        raise spark_error(ErrorCategory.PERMISSION_DENIED) from None
    except OSError:
        raise spark_error(ErrorCategory.UPSTREAM_ERROR) from None
