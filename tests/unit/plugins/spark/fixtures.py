"""Small generated Spark archives, never real cluster logs."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

APP = "application_1_42"


def events(attempt: str | None = "1", app: str = APP) -> list[dict[str, object]]:
    start: dict[str, object] = {"Event": "SparkListenerApplicationStart", "App ID": app}
    if attempt is not None:
        start["App Attempt ID"] = attempt
    return [
        {"Event": "SparkListenerLogStart", "Spark Version": "2.4.7.7.1.7.1000-141"},
        start,
        {"Event": "SparkListenerApplicationEnd", "Timestamp": 1000},
    ]


def encode(records: list[dict[str, object]]) -> bytes:
    return b"".join(json.dumps(event, separators=(",", ":")).encode() + b"\n" for event in records)


def archive_bytes(members: dict[str, bytes] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in (members or {APP + "_1": encode(events())}).items():
            archive.writestr(name, data)
    return buffer.getvalue()


def private_manifest(
    root: Path, attempts: tuple[str | None, ...] = (None, "1")
) -> tuple[Path, dict[str, Any]]:
    """Build exclusively synthetic, private local inspection evidence."""
    import hashlib

    directory = Path(root) / APP / "all" / ("a" * 32)
    directory.mkdir(parents=True, mode=0o700)
    for parent in (Path(root), directory.parent.parent, directory.parent, directory):
        parent.chmod(0o700)
    files: list[dict[str, Any]] = []
    for index, attempt in enumerate(attempts, 1):
        records = events(attempt)
        raw = encode(records)
        path = directory / f"eventlog-{index:04d}.jsonl"
        path.write_bytes(raw)
        path.chmod(0o600)
        files.append(
            dict(
                attempt_id=attempt,
                local_path=str(path),
                spark_version=records[0]["Spark Version"],
                size_bytes=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
                source_sha256="b" * 64,
                event_count=len(records),
                application_end_seen=True,
            )
        )
    path = directory / "manifest.json"
    body = dict(
        format_version=1,
        history_server_url="https://history.example",
        application_id=APP,
        requested_attempt_id=None,
        downloaded_at="2026-10-13T00:00:00Z",
        manifest_path=str(path),
        files=files,
    )
    path.write_text(json.dumps(body))
    path.chmod(0o600)
    return path, body
