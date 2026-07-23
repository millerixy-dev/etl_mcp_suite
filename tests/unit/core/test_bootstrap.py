"""Bootstrap CLI parsing, plugin selection, and lifecycle wiring tests."""

from __future__ import annotations

import json
import socket
from collections.abc import Mapping
from pathlib import Path

import pytest

from mcp_stdio.bootstrap import construct_runtime, main, parse_args
from mcp_stdio.core.config import ConfigError
from mcp_stdio.core.server import StdioMcpServer


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


def test_parse_args_requires_plugin() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--config", "x.yaml"])


def test_parse_args_config_is_optional() -> None:
    args = parse_args(["--plugin", "hive"])

    assert args.plugin == "hive"
    assert args.config is None
    assert args.debug is False


def test_parse_args_parses_plugin_config_and_debug() -> None:
    args = parse_args(["--plugin", "hive", "--config", "/tmp/hive.yaml", "--debug"])

    assert args.plugin == "hive"
    assert args.config == "/tmp/hive.yaml"
    assert args.debug is True


def test_parse_args_debug_defaults_false() -> None:
    args = parse_args(["--plugin", "hive", "--config", "/tmp/hive.yaml"])

    assert args.debug is False


def test_construct_runtime_rejects_unknown_plugin_without_dynamic_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = parse_args(["--plugin", "bogus", "--config", "/tmp/x.yaml"])

    with pytest.raises(ConfigError) as exc_info:
        construct_runtime(args, environ={})

    assert "unknown plugin" in str(exc_info.value)


def test_construct_runtime_rejects_mismatched_config_plugin(tmp_path: Path) -> None:
    path = tmp_path / "zeppelin.yaml"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "plugin": "zeppelin",
                "settings": {},
                "secrets": {},
            }
        ),
        encoding="utf-8",
    )
    args = parse_args(["--plugin", "hive", "--config", str(path)])

    with pytest.raises(ConfigError):
        construct_runtime(args, environ={})


def test_construct_runtime_builds_hive_runtime_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_network(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("startup attempted network access")

    monkeypatch.setattr(socket, "create_connection", reject_network)
    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_network)
    monkeypatch.setattr(socket, "getaddrinfo", reject_network)
    monkeypatch.setattr(socket, "gethostbyname", reject_network)

    config = _write_hive_config(tmp_path / "hive.json")
    args = parse_args(["--plugin", "hive", "--config", str(config)])
    environment: Mapping[str, str] = {
        "HIVE_USERNAME": "startup-user",
        "HIVE_PASSWORD": "startup-password",
    }

    runtime = construct_runtime(args, environ=environment)

    assert runtime.name == "hive"
    assert set(runtime.redaction_values) == {"startup-user", "startup-password"}


def test_construct_runtime_registers_exact_hive_tool_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_network(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("startup attempted network access")

    monkeypatch.setattr(socket, "create_connection", reject_network)
    monkeypatch.setattr(socket.socket, "connect", reject_network)

    config = _write_hive_config(tmp_path / "hive.json")
    args = parse_args(["--plugin", "hive", "--config", str(config)])
    environment: Mapping[str, str] = {
        "HIVE_USERNAME": "u",
        "HIVE_PASSWORD": "p",
    }

    runtime = construct_runtime(args, environ=environment)
    server = StdioMcpServer(runtime)

    assert sorted(server.tool_names()) == ["get_table_schema", "list_databases", "list_tables"]


def test_main_exits_nonzero_on_unknown_plugin(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--plugin", "bogus", "--config", "/tmp/missing.yaml"])

    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "unknown plugin" in captured.err


def test_construct_runtime_env_only_without_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_network(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("startup attempted network access")

    monkeypatch.setattr(socket, "create_connection", reject_network)
    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_network)

    args = parse_args(["--plugin", "hive"])
    environment: Mapping[str, str] = {
        "HIVE_HOST": "env-host.example.internal",
        "HIVE_PORT": "10000",
        "HIVE_DATABASE": "default",
        "HIVE_USERNAME": "env-user",
        "HIVE_PASSWORD": "env-password",
    }

    runtime = construct_runtime(args, environ=environment)

    assert runtime.name == "hive"
    assert set(runtime.redaction_values) == {"env-user", "env-password"}


def test_main_env_only_missing_required_env_exits_nonzero(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable in (
        "HIVE_HOST",
        "HIVE_PORT",
        "HIVE_DATABASE",
        "HIVE_USERNAME",
        "HIVE_PASSWORD",
        "HIVE_CACHE_TTL_SECONDS",
        "MCP_STDIO__SETTINGS__HOST",
    ):
        monkeypatch.delenv(variable, raising=False)

    with pytest.raises(SystemExit) as exc_info:
        main(["--plugin", "hive"])

    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "HIVE_HOST" in captured.err
