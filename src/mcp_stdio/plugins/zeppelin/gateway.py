"""MCP- and httpx-independent Zeppelin gateway contract."""

from __future__ import annotations

from typing import Protocol

from mcp_stdio.core.errors import ToolError
from mcp_stdio.plugins.zeppelin.models import (
    NotebookTreeNode,
    OutputItem,
    ParagraphStatus,
    SafeErrorDetail,
)


class ZeppelinGatewayError(RuntimeError):
    """A categorized, safe failure crossing the Zeppelin gateway boundary."""

    def __init__(self, tool_error: ToolError) -> None:
        self.tool_error = tool_error
        super().__init__(tool_error.message)


class ZeppelinGateway(Protocol):
    """REST operations required by the Zeppelin application service."""

    async def list_notebooks(self) -> tuple[NotebookTreeNode, ...]:
        """Return the notebook directory tree."""

        ...

    async def create_notebook(self, name: str) -> str:
        """Create a notebook and return its opaque ID."""

        ...

    async def add_paragraph(
        self,
        notebook_id: str,
        title: str,
        interpreter: str,
        body: str,
    ) -> str:
        """Add a paragraph and return its opaque ID."""

        ...

    async def run_paragraph(self, notebook_id: str, paragraph_id: str) -> ParagraphStatus:
        """Start paragraph execution and return the current normalized status."""

        ...

    async def get_paragraph_status(
        self, notebook_id: str, paragraph_id: str
    ) -> ParagraphStatus:
        """Return the current normalized paragraph status."""

        ...

    async def get_paragraph_result(
        self, notebook_id: str, paragraph_id: str
    ) -> tuple[ParagraphStatus, tuple[OutputItem, ...], SafeErrorDetail | None, bool]:
        """Return status, bounded outputs, optional error, and truncation flag."""

        ...

    async def close(self) -> None:
        """Close owned HTTP resources."""

        ...
