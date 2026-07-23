"""Hive plugin composition boundary."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
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

    def __init__(self, tools: HiveToolAdapter, *, redaction_values: Iterable[str] = ()) -> None:
        self._tools = tools
        self._redaction_values = tuple(value for value in redaction_values if value)
        self._closed = False

    @property
    def name(self) -> BuiltinPluginName:
        return "hive"

    @property
    def redaction_values(self) -> tuple[str, ...]:
        return self._redaction_values

    def register_tools(self, registrar: ToolRegistrar) -> None:
        self._tools.register_tools(registrar)

    async def close(self) -> None:
        self._closed = True


def _create_runtime(
    config_path: Path | None,
    environ: Mapping[str, str] | None,
) -> PluginRuntime:
    loaded = load_config(
        config_path,
        expected_plugin="hive",
        settings_type=HiveSettings,
        secrets_type=HiveSecrets,
        environ=environ,
        env_prefix="HIVE",
    )
    gateway = PyHiveMetadataAdapter(
        settings=loaded.settings,
        secrets=loaded.secrets,
    )
    service = HiveSchemaService(
        gateway=gateway,
        cache=HiveMetadataCache(loaded.settings.cache_ttl_seconds),
    )
    secret_values = (
        loaded.secrets.username.get_secret_value(),
        loaded.secrets.password.get_secret_value(),
    )
    tools = HiveToolAdapter(service=service, secret_values=secret_values)
    return HiveRuntime(tools, redaction_values=secret_values)


PLUGIN_DEFINITION = PluginDefinition(name="hive", runtime_builder=_create_runtime)
