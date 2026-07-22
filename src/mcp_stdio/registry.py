"""Explicit registry for the fixed built-in plugin set."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType

from mcp_stdio.contracts.plugin import PluginDefinition
from mcp_stdio.core.config import ConfigError

PluginDefinitionLoader = Callable[[], PluginDefinition]


def _load_hive() -> PluginDefinition:
    from mcp_stdio.plugins.hive.plugin import PLUGIN_DEFINITION

    return PLUGIN_DEFINITION


def _load_zeppelin() -> PluginDefinition:
    from mcp_stdio.plugins.zeppelin.plugin import PLUGIN_DEFINITION

    return PLUGIN_DEFINITION


def _load_dolphinscheduler() -> PluginDefinition:
    from mcp_stdio.plugins.dolphinscheduler.plugin import PLUGIN_DEFINITION

    return PLUGIN_DEFINITION


BUILTIN_PLUGIN_LOADERS: Mapping[str, PluginDefinitionLoader] = MappingProxyType(
    {
        "hive": _load_hive,
        "zeppelin": _load_zeppelin,
        "dolphinscheduler": _load_dolphinscheduler,
    }
)


def get_plugin_definition(name: str) -> PluginDefinition:
    """Return a statically imported definition or reject the name safely."""

    try:
        loader = BUILTIN_PLUGIN_LOADERS[name]
    except KeyError:
        raise ConfigError("unknown plugin") from None
    return loader()
