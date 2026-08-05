"""Zeppelin MCP tool adapter contract tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from mcp_stdio.bootstrap import construct_runtime, parse_args
from mcp_stdio.core.server import StdioMcpServer


def _write_zeppelin_config(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "plugin": "zeppelin",
                "settings": {
                    "base_url": "https://zeppelin.example/gateway/zeppelin",
                    "allowed_interpreters": ["spark"],
                },
                "secrets": {},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_zeppelin_registers_exact_eight_tool_set(tmp_path: Path) -> None:
    def reject_network(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("startup attempted network access")

    import builtins

    original_import = builtins.__import__

    config = _write_zeppelin_config(tmp_path / "zeppelin.json")
    args = parse_args(["--plugin", "zeppelin", "--config", str(config)])
    environment: Mapping[str, str] = {}

    runtime = construct_runtime(args, environ=environment)
    server = StdioMcpServer(runtime)

    assert sorted(server.tool_names()) == [
        "add_paragraph",
        "cancel_paragraph",
        "create_notebook",
        "get_paragraph_result",
        "get_paragraph_status",
        "list_notebooks",
        "restart_interpreter",
        "run_paragraph",
    ]
    builtins.__import__ = original_import


def test_add_paragraph_takes_no_interpreter_input() -> None:
    import inspect

    from mcp_stdio.plugins.zeppelin.tools import ZeppelinToolAdapter

    params = set(inspect.signature(ZeppelinToolAdapter.add_paragraph).parameters) - {"self"}
    assert params == {"notebook_id", "title", "body"}


def test_restart_interpreter_takes_setting_id_input() -> None:
    import inspect

    from mcp_stdio.plugins.zeppelin.tools import ZeppelinToolAdapter

    params = set(inspect.signature(ZeppelinToolAdapter.restart_interpreter).parameters) - {"self"}
    assert params == {"setting_id"}
