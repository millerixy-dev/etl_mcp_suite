"""Explicit registry for the fixed built-in plugin set."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from mcp_stdio.contracts.plugin import PluginDefinition
from mcp_stdio.core.config import ConfigError
from mcp_stdio.plugins.dolphinscheduler.plugin import (
    PLUGIN_DEFINITION as DOLPHINSCHEDULER_PLUGIN,
)
from mcp_stdio.plugins.hive.plugin import PLUGIN_DEFINITION as HIVE_PLUGIN
from mcp_stdio.plugins.zeppelin.plugin import PLUGIN_DEFINITION as ZEPPELIN_PLUGIN

BUILTIN_PLUGINS: Mapping[str, PluginDefinition] = MappingProxyType(
    {
        "hive": HIVE_PLUGIN,
        "zeppelin": ZEPPELIN_PLUGIN,
        "dolphinscheduler": DOLPHINSCHEDULER_PLUGIN,
    }
)


def get_plugin_definition(name: str) -> PluginDefinition:
    """Return a statically imported definition or reject the name safely."""

    try:
        return BUILTIN_PLUGINS[name]
    except KeyError:
        raise ConfigError("unknown plugin") from None
