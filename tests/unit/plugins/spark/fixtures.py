"""Small generated Spark archives, never real cluster logs."""

from __future__ import annotations

import io
import json
import zipfile

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
