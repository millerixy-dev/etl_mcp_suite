"""Real stdio sessions with injected upstream transports; no live Zeppelin."""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).parents[2]
_INITIALIZE_REQUEST: dict[str, Any] = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "zeppelin-contract", "version": "0.0.0"},
    },
}
_INITIALIZED_NOTIFICATION: dict[str, Any] = {
    "jsonrpc": "2.0",
    "method": "notifications/initialized",
}
_TOOLS_LIST_REQUEST: dict[str, Any] = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list",
    "params": {},
}

_DRIVER = """
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch
from mcp_stdio.core.server import StdioMcpServer
from mcp_stdio.plugins.zeppelin.plugin import PLUGIN_DEFINITION
from tests.unit.plugins.zeppelin.test_plugin import write_config
from tests.unit.plugins.zeppelin.test_http_client import (
    DiscoveryTransport, DiscoverySockets, discovery_adapter,
)
from tests.unit.plugins.zeppelin.test_websocket_client import LifecycleSocket
transport = DiscoveryTransport()
socket = LifecycleSocket()
if sys.argv[2] == "error":
    socket.frames = ["invalid-secret-frame"]
gateway = discovery_adapter(transport, DiscoverySockets(socket))
with patch("mcp_stdio.plugins.zeppelin.plugin.ZeppelinHttpClient", return_value=gateway):
    runtime = PLUGIN_DEFINITION.create_runtime(write_config(Path(sys.argv[1])), environ={})
server = StdioMcpServer(runtime)
server.run()
print("CLEANUP " + json.dumps({"http": transport.closes, "socket": socket.closes,
    "running": sorted(socket.running)}), file=sys.stderr)
"""


def _send(process: subprocess.Popen[str], message: dict[str, Any]) -> None:
    assert process.stdin is not None
    process.stdin.write(json.dumps(message) + "\n")
    process.stdin.flush()


def _read(process: subprocess.Popen[str]) -> dict[str, Any]:
    assert process.stdout is not None
    ready, _, _ = select.select([process.stdout], [], [], 10)
    assert ready, "stdio response timed out"
    line = process.stdout.readline()
    assert line, "server exited before responding"
    message = json.loads(line)
    assert message["jsonrpc"] == "2.0"
    return message


@pytest.mark.parametrize("outcome", ["success", "error"])
def test_discovery_stdio_protocol_and_shutdown_cleanup(tmp_path: Path, outcome: str) -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", _DRIVER, str(tmp_path / "zeppelin.json"), outcome],
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
        assert messages[-1]["id"] == 1
        _send(process, _INITIALIZED_NOTIFICATION)
        _send(process, _TOOLS_LIST_REQUEST)
        messages.append(_read(process))
        assert messages[-1]["id"] == 2
        assert len(messages[-1]["result"]["tools"]) == 9
        assert {tool["name"] for tool in messages[-1]["result"]["tools"]} == {
            "list_notebooks",
            "create_notebook",
            "add_paragraph",
            "run_paragraph",
            "get_paragraph_status",
            "get_paragraph_result",
            "get_interpreter_bindings",
            "restart_interpreter",
            "cancel_paragraph",
        }
        _send(
            process,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "get_interpreter_bindings",
                    "arguments": {"notebook_id": "first"},
                },
            },
        )
        messages.append(_read(process))
        assert messages[-1]["id"] == 3
        result = messages[-1]["result"]
        assert result.get("isError", False) is (outcome == "error")
        text = result["content"][0]["text"]
        if outcome == "success":
            public = json.loads(text)
            assert public == {"notebook_id": "first", "bindings": []}
        else:
            public = json.loads(
                text.removeprefix("Error executing tool get_interpreter_bindings: ")
            )
            assert public["operation"] == "get_interpreter_bindings"
            assert public["category"] == "UNEXPECTED_RESPONSE"
        assert process.stdin is not None
        process.stdin.close()
        process.stdin = None
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr
        assert stdout == "", "unexpected output after the last JSON-RPC response"
        cleanup = [
            line.removeprefix("CLEANUP ")
            for line in stderr.splitlines()
            if line.startswith("CLEANUP ")
        ]
        assert len(cleanup) == 1
        assert json.loads(cleanup[0]) == {"http": 1, "socket": 1, "running": []}
        captured = json.dumps(messages) + stdout + stderr
        for secret in (
            "fake-user",
            "configured-user-sentinel",
            "configured-pass-sentinel",
            "ticket-1",
            "invalid-secret-frame",
        ):
            assert secret not in captured
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
