"""Minimal lifecycle contract shared by the runtime and plugin composition roots."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

BuiltinPluginName = Literal["hive", "zeppelin", "dolphinscheduler"]
ToolHandler = Callable[..., object]


class ToolRegistrar(Protocol):
    """Inbound registration boundary implemented by the MCP server adapter."""

    def add_tool(self, fn: ToolHandler, name: str | None = None) -> None:
        """Register one plugin-owned tool handler."""


class PluginRuntime(Protocol):
    """One selected plugin's locally constructed runtime lifecycle."""

    @property
    def name(self) -> BuiltinPluginName:
        """Return the runtime's canonical built-in name."""

        ...

    def register_tools(self, registrar: ToolRegistrar) -> None:
        """Register only this runtime's inbound tool adapters."""

    async def close(self) -> None:
        """Idempotently close resources owned by this runtime."""


PluginRuntimeBuilder = Callable[[Path, Mapping[str, str] | None], PluginRuntime]


@dataclass(frozen=True, slots=True)
class PluginDefinition:
    """A statically registered plugin name and its local composition boundary."""

    name: BuiltinPluginName
    runtime_builder: PluginRuntimeBuilder = field(repr=False)

    def create_runtime(
        self,
        config_path: str | Path,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> PluginRuntime:
        """Validate plugin config and construct a runtime through plugin-owned composition."""

        return self.runtime_builder(Path(config_path), environ)
