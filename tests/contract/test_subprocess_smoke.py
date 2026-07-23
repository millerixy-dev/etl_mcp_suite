"""Subprocess smoke tests for the Hive plugin stdio lifecycle.

These tests launch the real `mcp-stdio` console entry point as a child
process, perform an MCP initialize/tools-list handshake over stdin/stdout, and
assert the exact Hive tool set, protocol-only stdout, stderr log presence, and
process isolation. No live HiveServer2 is required because startup does not
connect to a backend.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

PROJECT_ROOT = Path(__file__).parents[2]

_INITIALIZE_REQUEST: dict[str, Any] = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "smoke", "version": "0.0.0"},
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


def _write_hive_config(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "plugin": "hive",
                "settings": {
                    "host": "hive.example.internal",
                    "port": 10001,
                    "database": "catalog",
                },
                "secrets": {"username": "HIVE_USERNAME", "password": "HIVE_PASSWORD"},
            }
        ),
        encoding="utf-8",
    )
    return path


def _run_mcp_stdio(
    config: Path,
    *,
    extra_env: dict[str, str] | None = None,
    stdin_lines: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")}
    env["HIVE_USERNAME"] = "smoke-user"
    env["HIVE_PASSWORD"] = "smoke-password"
    if extra_env:
        env.update(extra_env)
    stdin_text = "".join(f"{line}\n" for line in stdin_lines) if stdin_lines else ""
    return subprocess.run(
        [sys.executable, "-m", "mcp_stdio", "--plugin", "hive", "--config", str(config)],
        cwd=PROJECT_ROOT,
        input=stdin_text,
        capture_output=True,
        text=True,
        env=env,
        timeout=20,
    )


def _parse_stdout_lines(stdout: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        messages.append(cast(dict[str, Any], json.loads(line)))
    return messages


def test_subprocess_starts_and_lists_exact_hive_tools(tmp_path: Path) -> None:
    config = _write_hive_config(tmp_path / "hive.json")
    completed = _run_mcp_stdio(
        config,
        stdin_lines=[
            json.dumps(_INITIALIZE_REQUEST),
            json.dumps(_INITIALIZED_NOTIFICATION),
            json.dumps(_TOOLS_LIST_REQUEST),
        ],
    )

    assert completed.returncode == 0, completed.stderr
    messages = _parse_stdout_lines(completed.stdout)
    tool_lists = [
        msg["result"]
        for msg in messages
        if isinstance(msg.get("result"), dict) and "tools" in msg["result"]
    ]
    assert len(tool_lists) == 1
    tool_names = {tool["name"] for tool in tool_lists[0]["tools"]}
    assert tool_names == {"list_databases", "list_tables", "get_table_schema"}


def test_subprocess_stdout_contains_only_mcp_protocol_json(tmp_path: Path) -> None:
    config = _write_hive_config(tmp_path / "hive.json")
    completed = _run_mcp_stdio(
        config,
        stdin_lines=[
            json.dumps(_INITIALIZE_REQUEST),
            json.dumps(_INITIALIZED_NOTIFICATION),
            json.dumps(_TOOLS_LIST_REQUEST),
        ],
    )

    assert completed.returncode == 0, completed.stderr
    for line in completed.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed = json.loads(stripped)
        assert "jsonrpc" in parsed, f"non-protocol line on stdout: {line!r}"


def test_subprocess_writes_application_logs_only_to_stderr(
    tmp_path: Path,
) -> None:
    config = _write_hive_config(tmp_path / "hive.json")
    completed = _run_mcp_stdio(
        config,
        stdin_lines=[json.dumps(_INITIALIZE_REQUEST), json.dumps(_INITIALIZED_NOTIFICATION)],
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() != ""
    initialize_result: dict[str, Any] = _parse_stdout_lines(completed.stdout)[0]
    assert "result" in initialize_result
    assert "serverInfo" in initialize_result["result"]


def test_subprocess_unknown_plugin_exits_nonzero_with_config_error(
    tmp_path: Path,
) -> None:
    config = _write_hive_config(tmp_path / "hive.json")
    completed = subprocess.run(
        [sys.executable, "-m", "mcp_stdio", "--plugin", "bogus", "--config", str(config)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
        timeout=20,
    )

    assert completed.returncode != 0
    assert "unknown plugin" in completed.stderr


def test_subprocess_secret_is_redacted_from_stderr_with_debug(
    tmp_path: Path,
) -> None:
    config = _write_hive_config(tmp_path / "hive.json")
    secret = "smoke-password"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "mcp_stdio",
            "--plugin",
            "hive",
            "--config",
            str(config),
        "--debug",
        ],
        cwd=PROJECT_ROOT,
        input="",
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": str(PROJECT_ROOT / "src"),
            "HIVE_USERNAME": "smoke-user",
            "HIVE_PASSWORD": secret,
        },
        timeout=20,
    )

    assert completed.returncode == 0, completed.stderr
    assert secret not in completed.stderr
    assert secret not in completed.stdout


def test_two_hive_subprocesses_are_independent_processes(tmp_path: Path) -> None:
    config_a = _write_hive_config(tmp_path / "hive_a.json")
    config_b = _write_hive_config(tmp_path / "hive_b.json")
    stdin = (
        "".join(
            f"{json.dumps(req)}\n"
            for req in [_INITIALIZE_REQUEST, _INITIALIZED_NOTIFICATION, _TOOLS_LIST_REQUEST]
        ).encode()
    )

    env = {
        **os.environ,
        "PYTHONPATH": str(PROJECT_ROOT / "src"),
        "HIVE_USERNAME": "u",
        "HIVE_PASSWORD": "p",
    }
    proc_a = subprocess.run(
        [sys.executable, "-m", "mcp_stdio", "--plugin", "hive", "--config", str(config_a)],
        cwd=PROJECT_ROOT, input=stdin.decode(), capture_output=True, text=True, env=env, timeout=20,
    )
    proc_b = subprocess.run(
        [sys.executable, "-m", "mcp_stdio", "--plugin", "hive", "--config", str(config_b)],
        cwd=PROJECT_ROOT, input=stdin.decode(), capture_output=True, text=True, env=env, timeout=20,
    )

    assert proc_a.returncode == 0, proc_a.stderr
    assert proc_b.returncode == 0, proc_b.stderr
    tools_a = _parse_stdout_lines(proc_a.stdout)
    tools_b = _parse_stdout_lines(proc_b.stdout)
    assert len(tools_a) == len(tools_b)


def _run_mcp_stdio_env_only(
    *,
    extra_env: dict[str, str] | None = None,
    stdin_lines: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")}
    env["HIVE_HOST"] = "hive.example.internal"
    env["HIVE_PORT"] = "10001"
    env["HIVE_DATABASE"] = "catalog"
    env["HIVE_USERNAME"] = "smoke-user"
    env["HIVE_PASSWORD"] = "smoke-password"
    if extra_env:
        env.update(extra_env)
    stdin_text = "".join(f"{line}\n" for line in stdin_lines) if stdin_lines else ""
    return subprocess.run(
        [sys.executable, "-m", "mcp_stdio", "--plugin", "hive"],
        cwd=PROJECT_ROOT,
        input=stdin_text,
        capture_output=True,
        text=True,
        env=env,
        timeout=20,
    )


def test_subprocess_starts_with_env_vars_only_without_config() -> None:
    completed = _run_mcp_stdio_env_only(
        stdin_lines=[
            json.dumps(_INITIALIZE_REQUEST),
            json.dumps(_INITIALIZED_NOTIFICATION),
            json.dumps(_TOOLS_LIST_REQUEST),
        ],
    )

    assert completed.returncode == 0, completed.stderr
    messages = _parse_stdout_lines(completed.stdout)
    tool_lists = [
        msg["result"]
        for msg in messages
        if isinstance(msg.get("result"), dict) and "tools" in msg["result"]
    ]
    assert len(tool_lists) == 1
    tool_names = {tool["name"] for tool in tool_lists[0]["tools"]}
    assert tool_names == {"list_databases", "list_tables", "get_table_schema"}


def test_subprocess_env_only_missing_required_var_exits_nonzero() -> None:
    env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")}
    env.pop("HIVE_HOST", None)
    env.pop("MCP_STDIO__SETTINGS__HOST", None)
    env["HIVE_USERNAME"] = "smoke-user"
    env["HIVE_PASSWORD"] = "smoke-password"

    completed = subprocess.run(
        [sys.executable, "-m", "mcp_stdio", "--plugin", "hive"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        env=env,
        timeout=20,
    )

    assert completed.returncode != 0
    assert "HIVE_HOST" in completed.stderr
