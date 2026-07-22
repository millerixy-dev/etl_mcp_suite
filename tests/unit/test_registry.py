from __future__ import annotations

import ast
import builtins
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from mcp_stdio.contracts.plugin import (
    BuiltinPluginName,
    PluginDefinition,
    PluginRuntime,
    ToolHandler,
    ToolRegistrar,
)
from mcp_stdio.core.config import ConfigError
from mcp_stdio.plugins.dolphinscheduler.plugin import (
    PLUGIN_DEFINITION as DOLPHINSCHEDULER_PLUGIN,
)
from mcp_stdio.plugins.hive.plugin import PLUGIN_DEFINITION as HIVE_PLUGIN
from mcp_stdio.plugins.zeppelin.plugin import PLUGIN_DEFINITION as ZEPPELIN_PLUGIN
from mcp_stdio.registry import BUILTIN_PLUGINS, get_plugin_definition

PROJECT_ROOT = Path(__file__).parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src" / "mcp_stdio"


class RecordingRegistrar:
    def __init__(self) -> None:
        self.tools: list[tuple[ToolHandler, str | None]] = []

    def add_tool(self, fn: ToolHandler, name: str | None = None) -> None:
        self.tools.append((fn, name))


class RecordingRuntime:
    def __init__(self, name: BuiltinPluginName) -> None:
        self._name: BuiltinPluginName = name
        self.closed = False

    @property
    def name(self) -> BuiltinPluginName:
        return self._name

    def register_tools(self, registrar: ToolRegistrar) -> None:
        registrar.add_tool(self._tool, name="recording_tool")

    async def close(self) -> None:
        self.closed = True

    @staticmethod
    def _tool() -> dict[str, bool]:
        return {"ok": True}


def test_registry_contains_only_the_three_static_builtin_definitions() -> None:
    assert tuple(BUILTIN_PLUGINS) == ("hive", "zeppelin", "dolphinscheduler")
    assert BUILTIN_PLUGINS == {
        "hive": HIVE_PLUGIN,
        "zeppelin": ZEPPELIN_PLUGIN,
        "dolphinscheduler": DOLPHINSCHEDULER_PLUGIN,
    }


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("hive", HIVE_PLUGIN),
        ("zeppelin", ZEPPELIN_PLUGIN),
        ("dolphinscheduler", DOLPHINSCHEDULER_PLUGIN),
    ],
)
def test_supported_selection_returns_the_statically_imported_definition(
    name: str,
    expected: PluginDefinition,
) -> None:
    assert get_plugin_definition(name) is expected


def test_unknown_plugin_fails_with_a_fixed_config_error_before_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_import(*args: object, **kwargs: object) -> object:
        raise AssertionError("selection attempted a dynamic import")

    monkeypatch.setattr(builtins, "__import__", reject_import)

    with pytest.raises(ConfigError) as exc_info:
        get_plugin_definition("caller.controlled.module")

    assert str(exc_info.value) == "CONFIG_ERROR: unknown plugin"


def test_definition_bridges_registration_and_async_cleanup_without_mcp_types(
    tmp_path: Path,
) -> None:
    calls: list[tuple[Path, Mapping[str, str] | None]] = []
    runtime = RecordingRuntime("hive")

    def build(
        config_path: Path,
        environ: Mapping[str, str] | None,
    ) -> PluginRuntime:
        calls.append((config_path, environ))
        return runtime

    definition = PluginDefinition(name="hive", runtime_builder=build)
    environment = {"HIVE_USERNAME": "placeholder"}

    selected_runtime = definition.create_runtime(
        tmp_path / "hive.yaml",
        environ=environment,
    )
    registrar = RecordingRegistrar()
    selected_runtime.register_tools(registrar)

    assert selected_runtime is runtime
    assert calls == [(tmp_path / "hive.yaml", environment)]
    assert [(name, handler()) for handler, name in registrar.tools] == [
        ("recording_tool", {"ok": True})
    ]


@pytest.mark.asyncio
async def test_runtime_cleanup_is_asynchronous() -> None:
    runtime = RecordingRuntime("zeppelin")

    await runtime.close()

    assert runtime.closed is True


@pytest.mark.parametrize("definition", BUILTIN_PLUGINS.values())
def test_placeholder_runtime_construction_fails_clearly(
    definition: PluginDefinition,
    tmp_path: Path,
) -> None:
    with pytest.raises(NotImplementedError, match=rf"^{definition.name} plugin runtime"):
        definition.create_runtime(tmp_path / "config.yaml", environ={})


def test_registry_and_plugin_composition_sources_prohibit_dynamic_discovery() -> None:
    source_paths = [
        SOURCE_ROOT / "registry.py",
        SOURCE_ROOT / "plugins" / "hive" / "plugin.py",
        SOURCE_ROOT / "plugins" / "zeppelin" / "plugin.py",
        SOURCE_ROOT / "plugins" / "dolphinscheduler" / "plugin.py",
    ]
    prohibited_modules = {"importlib", "pkgutil"}
    prohibited_calls = {
        "__import__",
        "entry_points",
        "glob",
        "import_module",
        "iterdir",
        "rglob",
        "walk",
    }

    for source_path in source_paths:
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        imported_modules = {
            alias.name.split(".", maxsplit=1)[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in (
                node.names
                if isinstance(node, ast.Import)
                else [ast.alias(name=node.module or "")]
            )
        }
        called_names = {
            node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Name, ast.Attribute))
        }

        assert imported_modules.isdisjoint(prohibited_modules)
        assert called_names.isdisjoint(prohibited_calls)


def test_importing_registry_does_not_attempt_a_network_connection() -> None:
    script = """
import socket

def reject_network(*args, **kwargs):
    raise AssertionError("registry import attempted network access")

socket.create_connection = reject_network
socket.socket.connect = reject_network
import mcp_stdio.registry
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
