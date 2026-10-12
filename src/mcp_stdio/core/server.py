"""Shared FastMCP stdio server adapter for one selected plugin runtime."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError as FastMCPToolError
from mcp.server.fastmcp.utilities.func_metadata import ArgModelBase, func_metadata
from mcp.types import ContentBlock
from mcp.types import Tool as MCPTool
from pydantic import ValidationError

from mcp_stdio.contracts.plugin import PluginRuntime, ToolHandler
from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation


class _ValidatedFastMCP(FastMCP[object]):
    """Reject raw invalid inputs before the SDK's convenience coercion."""

    def __init__(self, *, name: str, debug: bool) -> None:
        super().__init__(name=name, debug=debug)
        self.argument_models: dict[str, type[ArgModelBase]] = {}

    async def list_tools(self) -> list[MCPTool]:
        tools = await super().list_tools()
        for tool in tools:
            if model := self.argument_models.get(tool.name):
                tool.inputSchema = model.model_json_schema(by_alias=True)
        return tools

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> Sequence[ContentBlock] | dict[str, Any]:
        if model := self.argument_models.get(name):
            try:
                model.model_validate(arguments)
            except ValidationError:
                try:
                    operation = ToolOperation(name)
                except ValueError:
                    operation = ToolOperation.RUNTIME
                error = ToolError(
                    category=ErrorCategory.INVALID_INPUT, operation=operation, retryable=False
                )
                raise FastMCPToolError(json.dumps(error.to_dict(secret_values=()))) from None
        return await super().call_tool(name, arguments)


class StdioMcpServer:
    """A FastMCP stdio server that serves exactly one plugin runtime's tools."""

    def __init__(self, runtime: PluginRuntime, *, debug: bool = False) -> None:
        self._runtime = runtime
        self._fastmcp = _ValidatedFastMCP(name="mcp-stdio", debug=debug)
        self._tool_names: list[str] = []
        runtime.register_tools(self)

    def add_tool(self, fn: ToolHandler, name: str | None = None) -> None:
        """Register one plugin-owned tool handler with the MCP server."""

        self._fastmcp.add_tool(fn, name=name)
        tool_name = name if name is not None else getattr(fn, "__name__", "tool")
        model = func_metadata(fn).arg_model
        model.model_config.update(extra="forbid", hide_input_in_errors=True)
        model.model_rebuild(force=True)
        self._fastmcp.argument_models[tool_name] = model
        self._tool_names.append(name if name is not None else getattr(fn, "__name__", "tool"))

    def tool_names(self) -> list[str]:
        """Return the exact registered tool names in registration order."""

        return list(self._tool_names)

    async def serve(self) -> None:
        """Run the stdio session and close the runtime on any exit path."""

        try:
            await self._fastmcp.run_stdio_async()
        finally:
            await self._runtime.close()

    def run(self) -> None:
        """Run the stdio server on a fresh event loop until the session ends."""

        asyncio.run(self.serve())
