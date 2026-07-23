"""Shared FastMCP stdio server adapter for one selected plugin runtime."""

from __future__ import annotations

import asyncio

from mcp.server.fastmcp import FastMCP

from mcp_stdio.contracts.plugin import PluginRuntime, ToolHandler


class StdioMcpServer:
    """A FastMCP stdio server that serves exactly one plugin runtime's tools."""

    def __init__(self, runtime: PluginRuntime, *, debug: bool = False) -> None:
        self._runtime = runtime
        self._fastmcp: FastMCP[object] = FastMCP(name="mcp-stdio", debug=debug)
        self._tool_names: list[str] = []
        runtime.register_tools(self)

    def add_tool(self, fn: ToolHandler, name: str | None = None) -> None:
        """Register one plugin-owned tool handler with the MCP server."""

        self._fastmcp.add_tool(fn, name=name)
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
