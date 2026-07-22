"""Hive plugin composition boundary."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from mcp_stdio.contracts.plugin import (
    BuiltinPluginName,
    PluginDefinition,
    PluginRuntime,
    ToolRegistrar,
)
from mcp_stdio.core.config import load_config
from mcp_stdio.plugins.hive.cache import HiveMetadataCache
from mcp_stdio.plugins.hive.config import HiveSecrets, HiveSettings
from mcp_stdio.plugins.hive.pyhive import PyHiveMetadataAdapter
from mcp_stdio.plugins.hive.service import HiveSchemaService
from mcp_stdio.plugins.hive.tools import HiveToolAdapter


class HiveRuntime:
    """Locally composed Hive runtime with no long-lived upstream resources."""

    def __init__(self, tools: HiveToolAdapter) -> None:
        self._tools = tools
        self._closed = False

    @property
    def name(self) -> BuiltinPluginName:
        return "hive"

    def register_tools(self, registrar: ToolRegistrar) -> None:
        self._tools.register_tools(registrar)

    async def close(self) -> None:
        self._closed = True


def _create_runtime(
    config_path: Path,
    environ: Mapping[str, str] | None,
) -> PluginRuntime:
    loaded = load_config(
        config_path,
        expected_plugin="hive",
        settings_type=HiveSettings,
        secrets_type=HiveSecrets,
        environ=environ,
    )
    gateway = PyHiveMetadataAdapter(
        settings=loaded.settings,
        secrets=loaded.secrets,
    )
    service = HiveSchemaService(
        gateway=gateway,
        cache=HiveMetadataCache(loaded.settings.cache_ttl_seconds),
    )
    tools = HiveToolAdapter(
        service=service,
        secret_values=(
            loaded.secrets.username.get_secret_value(),
            loaded.secrets.password.get_secret_value(),
        ),
    )
    return HiveRuntime(tools)


PLUGIN_DEFINITION = PluginDefinition(name="hive", runtime_builder=_create_runtime)
