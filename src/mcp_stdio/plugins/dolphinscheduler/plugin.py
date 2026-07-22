"""DolphinScheduler plugin composition boundary."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from mcp_stdio.contracts.plugin import PluginDefinition, PluginRuntime


def _create_runtime(
    config_path: Path,
    environ: Mapping[str, str] | None,
) -> PluginRuntime:
    raise NotImplementedError("dolphinscheduler plugin runtime is not implemented yet")


PLUGIN_DEFINITION = PluginDefinition(
    name="dolphinscheduler",
    runtime_builder=_create_runtime,
)
