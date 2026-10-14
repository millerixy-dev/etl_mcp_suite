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
from tests.unit.plugins.spark.fixtures import archive_bytes, encode, events
from tests.unit.plugins.spark.test_http_client import Stream
calls = []
records = events() + [
    {"Event": "SparkListenerStageCompleted", "Stage Info": {
        "Stage ID": 17, "Stage Attempt ID": 0, "Submission Time": 1000,
        "Completion Time": 901000}},
]
for task_id, duration, data in [(7, 100, 100), (8, 900, 200)]:
    records.append({"Event": "SparkListenerTaskEnd", "Stage ID": 17,
        "Stage Attempt ID": 0, "Task End Reason": {"Reason": "Success"},
        "Task Info": {"Task ID": task_id, "Executor ID": "2",
                      "Launch Time": 10, "Finish Time": 10 + duration},
        "Task Metrics": {"Executor Run Time": duration - 20, "JVM GC Time": 0,
            "Input Metrics": {"Bytes Read": data},
            "Shuffle Read Metrics": {"Remote Bytes Read": duration,
                                     "Local Bytes Read": 0, "Fetch Wait Time": 10}}})
def handler(request):
    calls.append(request.url.path)
    if sys.argv[2] == "cache":
        raise AssertionError("cache hit made an HTTP request")
    if request.method == "POST":
        assert request.headers.get("Authorization", "").startswith("Basic ")
        return httpx.Response(200, headers={
            "Set-Cookie": "hadoop-jwt=synthetic-issued; Path=/; Secure"})
    assert "Authorization" not in request.headers
    if sys.argv[3] == "basic":
        assert request.headers["Cookie"] == "hadoop-jwt=synthetic-issued"
    return httpx.Response(404 if sys.argv[2] == "error" else 200,
                         stream=Stream([archive_bytes({"application_1_42_1": encode(records)})]))
def factory(**kwargs):
    return SparkEventLogAdapter(**kwargs, transport=httpx.MockTransport(handler))
with patch("mcp_stdio.plugins.spark.plugin.SparkEventLogAdapter", side_effect=factory):
    env = {
        "SPARK_HISTORY_SERVER_URL": "https://history.example",
        "SPARK_CACHE_DIR": sys.argv[1],
        "SPARK_GATEWAY_COOKIE": "session=synthetic-cookie",
    }
    if sys.argv[3] == "basic":
        del env["SPARK_GATEWAY_COOKIE"]
        env.update(SPARK_USERNAME="synthetic-user", SPARK_PASSWORD="synthetic-password",
                   SPARK_KNOX_SSO_URL="https://history.example/gateway/knoxsso/api/v1/websso")
    runtime = PLUGIN_DEFINITION.create_runtime(None, environ=env)
configure_logging(debug=True, secret_values=runtime.redaction_values)
StdioMcpServer(runtime).run()
print("CLEANUP " + json.dumps({"requests": len(calls)}), file=sys.stderr)
"""


def _session(root: Path, outcome: str, auth: str = "cookie") -> dict[str, Any]:
    process = subprocess.Popen(
        [sys.executable, "-c", _DRIVER, str(root), outcome, auth],
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
        assert [tool["name"] for tool in listing["result"]["tools"]] == [
            "fetch_spark_event_log",
            "inspect_spark_event_log",
            "query_spark_events",
            "get_spark_stage_metrics",
            "get_spark_task_distribution",
            "fetch_spark_executor_log",
        ]
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
        if outcome != "error":
            fetched = json.loads(reply["result"]["content"][0]["text"])
            immutable = {
                str(path): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in root.rglob("*")
                if path.is_file() and path.name != ".lock"
            }
            common = {"manifest_path": fetched["manifest_path"], "attempt_id": "1"}
            responses: list[dict[str, Any]] = []
            for request_id, name, arguments in [
                (4, "inspect_spark_event_log", common),
                (
                    5,
                    "query_spark_events",
                    {
                        **common,
                        "expected_sha256": fetched["files"][0]["sha256"],
                        "lines": [3],
                        "limit": 1,
                        "max_detail_chars": 32768,
                    },
                ),
                (6, "query_spark_events", {**common, "expected_sha256": "a" * 64}),
                (7, "inspect_spark_event_log", {**common, "unknown": "forbidden-secret"}),
                (
                    8,
                    "get_spark_stage_metrics",
                    {**common, "expected_sha256": fetched["files"][0]["sha256"]},
                ),
                (
                    9,
                    "get_spark_task_distribution",
                    {
                        **common,
                        "expected_sha256": fetched["files"][0]["sha256"],
                        "stage_id": 17,
                        "stage_attempt_id": 0,
                        "limit": 1,
                    },
                ),
                (10, "get_spark_stage_metrics", {**common, "expected_sha256": "a" * 64}),
                (
                    11,
                    "get_spark_task_distribution",
                    {**common, "expected_sha256": "a" * 64, "stage_id": 17, "stage_attempt_id": 0},
                ),
            ]:
                _send(
                    process,
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "tools/call",
                        "params": {"name": name, "arguments": arguments},
                    },
                )
                response = _read(process)
                messages.append(response)
                responses.append(response["result"])
            overview = json.loads(responses[0]["content"][0]["text"])
            query = json.loads(responses[1]["content"][0]["text"])
            assert set(overview) == {
                "snapshot",
                "spark_version",
                "event_count",
                "event_types",
                "event_types_omitted",
                "signals",
                "task_end_count",
                "task_end_reasons",
                "reasons_omitted",
                "evidence",
                "evidence_omitted",
                "coverage",
            }
            assert set(query) == {
                "snapshot",
                "matched_count",
                "task_end_count",
                "task_end_reasons",
                "reasons_omitted",
                "events",
                "returned_count",
                "next_after_line",
                "coverage",
            }
            assert overview["event_count"] == 6
            stages = json.loads(responses[4]["content"][0]["text"])
            distribution = json.loads(responses[5]["content"][0]["text"])
            assert set(stages) == {
                "snapshot",
                "coverage",
                "matched_stage_attempt_count",
                "unassigned_task_end_count",
                "stages",
                "stages_omitted",
            }
            assert stages["matched_stage_attempt_count"] == 1
            assert stages["stages"][0]["duration_ms"] == 900000
            assert stages["stages"][0]["input_bytes"] == {
                "total": 300,
                "valid_count": 2,
                "missing_count": 0,
            }
            assert stages["stages"][0]["shuffle_read_bytes"]["total"] == 1000
            assert distribution["distributions"]["duration_ms"] == {
                "valid_count": 2,
                "missing_count": 0,
                "min": 100,
                "p50": 100,
                "p95": 900,
                "max": 900,
            }
            assert distribution["ranked_task_count"] == 2
            assert distribution["tasks_omitted"] == 1
            assert distribution["top_tasks"][0]["task_id"] == 8
            assert distribution["top_tasks"][0]["ref"] == {
                "sha256": overview["snapshot"]["sha256"],
                "line": 6,
            }
            for index, name in [(6, "get_spark_stage_metrics"), (7, "get_spark_task_distribution")]:
                assert "UNEXPECTED_RESPONSE" in responses[index]["content"][0]["text"]
                assert name in responses[index]["content"][0]["text"]
            assert query["events"][0]["ref"] == {
                "sha256": overview["snapshot"]["sha256"],
                "line": 3,
            }
            assert query["matched_count"] == query["returned_count"] == 1
            assert query["next_after_line"] is None
            assert "UNEXPECTED_RESPONSE" in responses[2]["content"][0]["text"]
            assert "query_spark_events" in responses[2]["content"][0]["text"]
            assert "INVALID_INPUT" in responses[3]["content"][0]["text"]
            assert "inspect_spark_event_log" in responses[3]["content"][0]["text"]
            assert "forbidden-secret" not in json.dumps(messages)
            assert immutable == {
                str(path): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in root.rglob("*")
                if path.is_file() and path.name != ".lock"
            }
        assert process.stdin is not None
        process.stdin.close()
        process.stdin = None
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr
        assert stdout == ""
        for value in ("synthetic-cookie", "synthetic-password", "synthetic-issued"):
            assert value not in json.dumps(messages) + stderr
        cleanup = [
            json.loads(line.removeprefix("CLEANUP "))
            for line in stderr.splitlines()
            if line.startswith("CLEANUP ")
        ]
        assert cleanup == [{"requests": 0 if outcome == "cache" else (2 if auth == "basic" else 1)}]
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


def test_basic_stdio_exchange_then_cross_process_cache(tmp_path: Path) -> None:
    root = tmp_path / "l3"
    first = _session(root, "success", "basic")
    assert not first.get("isError", False)
    hit = _session(root, "cache", "basic")
    assert not hit.get("isError", False)
    assert json.loads(hit["content"][0]["text"])["cache_hit"]


_LOG_DRIVER = """
import json, sys
from unittest.mock import patch
import httpx
from mcp_stdio.core.server import StdioMcpServer
from mcp_stdio.plugins.spark.cache import SparkEventLogAdapter
from mcp_stdio.plugins.spark.executor_logs import SparkExecutorLogAdapter
from mcp_stdio.plugins.spark.plugin import PLUGIN_DEFINITION
from tests.unit.plugins.spark.fixtures import archive_bytes, encode, events
from tests.unit.plugins.spark.test_http_client import Stream
root = "https://history.example/gateway/test"
container = "container_e83_1_0042_02_000001"
records = events("2")
records[1]["Driver Logs"] = {"stdout":
    f"http://node.example:8042/node/containerlogs/{container}/owner/stdout?start=-4096"}
calls = []
def handler(request):
    calls.append(request.url.path)
    assert "Authorization" not in request.headers
    assert request.headers["Cookie"] == "session=synthetic-cookie"
    if "/api/v1/" in request.url.path:
        return httpx.Response(200, stream=Stream([
            archive_bytes({"application_1_42_2": encode(records)})]))
    if "/yarn/" in request.url.path:
        return httpx.Response(307, headers={"location":
            f"{root}/jobhistory/joblogs/node.example:8041/{container}/{container}/owner/stdout"
            "?scheme=http&host=jhs.example&port=19888"})
    text = "token=synthetic-private\\nEOF"
    html = f"<p>Log Type: stdout</p><p>Log Length: {len(text)}</p><pre>{text}</pre>"
    return httpx.Response(200, stream=Stream([html.encode()]))
def event_factory(**kwargs):
    return SparkEventLogAdapter(**kwargs, transport=httpx.MockTransport(handler))
def log_factory(**kwargs):
    return SparkExecutorLogAdapter(**kwargs, transport=httpx.MockTransport(handler))
with patch("mcp_stdio.plugins.spark.plugin.SparkEventLogAdapter", side_effect=event_factory), \\
     patch("mcp_stdio.plugins.spark.plugin.SparkExecutorLogAdapter", side_effect=log_factory):
    runtime = PLUGIN_DEFINITION.create_runtime(None, environ={
        "SPARK_HISTORY_SERVER_URL": root+"/sparkhistory", "SPARK_CACHE_DIR": sys.argv[1],
        "SPARK_GATEWAY_COOKIE": "session=synthetic-cookie",
        "SPARK_EXECUTOR_LOG_NODE_MANAGER_PATH": "/yarn/nodemanager/node",
        "SPARK_EXECUTOR_LOG_ALLOWED_UPSTREAMS":
            '["http://node.example:8042","http://jhs.example:19888"]'})
StdioMcpServer(runtime).run()
print("CLEANUP " + json.dumps({"requests":len(calls)}), file=sys.stderr)
"""


def test_executor_log_real_stdio_with_mock_gateway(tmp_path: Path) -> None:
    import hashlib

    process = subprocess.Popen(
        [sys.executable, "-c", _LOG_DRIVER, str(tmp_path / "l3")],
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
    try:
        _send(process, _INITIALIZE_REQUEST)
        _read(process)
        _send(process, _INITIALIZED_NOTIFICATION)
        _send(process, _TOOLS_LIST_REQUEST)
        listing = _read(process)
        assert len(listing["result"]["tools"]) == 6
        for index in range(2):
            _send(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 3 + index,
                    "method": "tools/call",
                    "params": {
                        "name": "fetch_spark_executor_log",
                        "arguments": {
                            "application_id": "application_1_42",
                            "attempt_id": "2",
                            "executor_id": "driver",
                            "log_type": "stdout",
                        },
                    },
                },
            )
            reply = _read(process)
            assert not reply["result"].get("isError")
            value = json.loads(reply["result"]["content"][0]["text"])
            assert len(value) == 12 and value["container_id"] == "container_e83_1_0042_02_000001"
            raw = Path(value["local_path"]).read_bytes()
            assert raw.endswith(b"EOF") and b"synthetic-private" not in raw
            assert hashlib.sha256(raw).hexdigest() == value["sha256"]
            assert "synthetic-private" not in json.dumps(reply)
        assert process.stdin is not None
        process.stdin.close()
        assert process.wait(timeout=10) == 0
        assert process.stderr is not None and process.stdout is not None
        assert '"requests": 5' in process.stderr.read()
        assert process.stdout.read() == ""
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
