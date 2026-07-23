"""Zeppelin plugin composition boundary."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from mcp_stdio.contracts.plugin import PluginDefinition, PluginRuntime


def _create_runtime(
    config_path: Path | None,
    environ: Mapping[str, str] | None,
) -> PluginRuntime:
    raise NotImplementedError("zeppelin plugin runtime is not implemented yet")


PLUGIN_DEFINITION = PluginDefinition(name="zeppelin", runtime_builder=_create_runtime)
