"""Real Spark stdio sessions against a mock History Server."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from tests.contract.test_zeppelin_stdio import (
    _INITIALIZE_REQUEST,
    _INITIALIZED_NOTIFICATION,
    _TOOLS_LIST_REQUEST,
    _read,
    _send,
)

PROJECT_ROOT = Path(__file__).parents[2]
_DRIVER = """
import json, sys
from unittest.mock import patch
import httpx
from mcp_stdio.core.logging import configure_logging
from mcp_stdio.core.server import StdioMcpServer
from mcp_stdio.plugins.spark.cache import SparkEventLogAdapter
from mcp_stdio.plugins.spark.plugin import PLUGIN_DEFINITION
from tests.unit.plugins.spark.fixtures import archive_bytes
from tests.unit.plugins.spark.test_http_client import Stream
calls = []
def handler(request):
    calls.append(request.url.path)
    if sys.argv[2] == "cache":
        raise AssertionError("cache hit made an HTTP request")
    return httpx.Response(404 if sys.argv[2] == "error" else 200,
                         stream=Stream([archive_bytes()]))
def factory(**kwargs):
    return SparkEventLogAdapter(**kwargs, transport=httpx.MockTransport(handler))
with patch("mcp_stdio.plugins.spark.plugin.SparkEventLogAdapter", side_effect=factory):
    runtime = PLUGIN_DEFINITION.create_runtime(None, environ={
        "SPARK_HISTORY_SERVER_URL": "https://history.example",
        "SPARK_CACHE_DIR": sys.argv[1],
        "SPARK_GATEWAY_COOKIE": "session=synthetic-cookie",
    })
configure_logging(debug=True, secret_values=runtime.redaction_values)
StdioMcpServer(runtime).run()
print("CLEANUP " + json.dumps({"requests": len(calls)}), file=sys.stderr)
"""


def _session(root: Path, outcome: str) -> dict[str, Any]:
    process = subprocess.Popen(
        [sys.executable, "-c", _DRIVER, str(root), outcome],
        cwd=PROJECT_ROOT,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join([str(PROJECT_ROOT / "src"), str(PROJECT_ROOT)]),
        },
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    messages: list[dict[str, Any]] = []
    try:
        _send(process, _INITIALIZE_REQUEST)
        messages.append(_read(process))
        _send(process, _INITIALIZED_NOTIFICATION)
        _send(process, _TOOLS_LIST_REQUEST)
        listing = _read(process)
        assert [tool["name"] for tool in listing["result"]["tools"]] == ["fetch_spark_event_log"]
        _send(
            process,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "fetch_spark_event_log",
                    "arguments": {"application_id": "application_1_42", "attempt_id": "1"},
                },
            },
        )
        reply = _read(process)
        messages.append(reply)
        assert process.stdin is not None
        process.stdin.close()
        process.stdin = None
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr
        assert stdout == ""
        assert "synthetic-cookie" not in json.dumps(messages) + stderr
        cleanup = [
            json.loads(line.removeprefix("CLEANUP "))
            for line in stderr.splitlines()
            if line.startswith("CLEANUP ")
        ]
        assert cleanup == [{"requests": 0 if outcome == "cache" else 1}]
        return reply["result"]
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)


def test_stdio_download_then_restart_reuses_readable_files(tmp_path: Path) -> None:
    root = tmp_path / "l3"
    first = _session(root, "success")
    assert not first.get("isError", False)
    downloaded = json.loads(first["content"][0]["text"])
    file = Path(downloaded["files"][0]["local_path"])
    assert file.is_file()
    assert file.read_text().count("\n") == downloaded["files"][0]["event_count"]
    assert not list(root.rglob("*.zip"))
    reused = _session(root, "cache")
    hit = json.loads(reused["content"][0]["text"])
    assert hit["cache_hit"]
    assert hit["manifest_path"] == downloaded["manifest_path"]


def test_stdio_failure_is_safe_and_leaves_no_staging(tmp_path: Path) -> None:
    root = tmp_path / "l3"
    failed = _session(root, "error")
    assert failed["isError"]
    assert "NOT_FOUND" in failed["content"][0]["text"]
    assert not list(root.glob(".part-*"))
    assert not list(root.rglob("manifest.json"))
