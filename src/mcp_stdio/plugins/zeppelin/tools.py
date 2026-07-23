"""Inbound MCP tool adapters for the Zeppelin notebook surface."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Annotated, NoReturn

from mcp.server.fastmcp.exceptions import ToolError as FastMCPToolError
from pydantic import WithJsonSchema

from mcp_stdio.contracts.plugin import ToolRegistrar
from mcp_stdio.core.errors import ToolError, ToolOperation, unexpected_tool_error
from mcp_stdio.plugins.zeppelin.gateway import ZeppelinGatewayError
from mcp_stdio.plugins.zeppelin.models import (
    AddParagraphResult,
    CreateNotebookResult,
    NotebookTreeResult,
    ParagraphResult,
    ParagraphStatusResult,
    RunParagraphResult,
)
from mcp_stdio.plugins.zeppelin.service import ZeppelinNotebookService

ZeppelinToolString = Annotated[object, WithJsonSchema({"type": "string"})]


class ZeppelinToolAdapter:
    """Translate five typed inbound calls to the Zeppelin application service."""

    def __init__(
        self,
        *,
        service: ZeppelinNotebookService,
        secret_values: Iterable[str],
    ) -> None:
        self._service = service
        self._secret_values = tuple(value for value in secret_values if value)

    def register_tools(self, registrar: ToolRegistrar) -> None:
        """Register exactly the five approved Zeppelin tools."""

        registrar.add_tool(self.list_notebooks, name="list_notebooks")
        registrar.add_tool(self.create_notebook, name="create_notebook")
        registrar.add_tool(self.add_paragraph, name="add_paragraph")
        registrar.add_tool(self.run_paragraph, name="run_paragraph")
        registrar.add_tool(self.get_paragraph_status, name="get_paragraph_status")
        registrar.add_tool(self.get_paragraph_result, name="get_paragraph_result")

    async def list_notebooks(self) -> NotebookTreeResult:
        """List the Zeppelin notebook directory tree."""

        try:
            return await self._service.list_notebooks()
        except ZeppelinGatewayError as error:
            self._raise_tool_error(error.tool_error)
        except Exception as error:
            self._raise_tool_error(
                unexpected_tool_error(error, operation=ToolOperation.LIST_NOTEBOOKS)
            )

    async def create_notebook(self, name: ZeppelinToolString) -> CreateNotebookResult:
        """Create a Zeppelin notebook and return its opaque ID and name."""

        try:
            return await self._service.create_notebook(name)
        except ZeppelinGatewayError as error:
            self._raise_tool_error(error.tool_error)
        except Exception as error:
            self._raise_tool_error(
                unexpected_tool_error(error, operation=ToolOperation.CREATE_NOTEBOOK)
            )

    async def add_paragraph(
        self,
        notebook_id: ZeppelinToolString,
        title: ZeppelinToolString,
        interpreter: ZeppelinToolString,
        body: ZeppelinToolString,
    ) -> AddParagraphResult:
        """Add an allowlisted paragraph to an existing notebook."""

        try:
            return await self._service.add_paragraph(notebook_id, title, interpreter, body)
        except ZeppelinGatewayError as error:
            self._raise_tool_error(error.tool_error)
        except Exception as error:
            self._raise_tool_error(
                unexpected_tool_error(error, operation=ToolOperation.ADD_PARAGRAPH)
            )

    async def run_paragraph(
        self, notebook_id: ZeppelinToolString, paragraph_id: ZeppelinToolString
    ) -> RunParagraphResult:
        """Start paragraph execution without polling to completion."""

        try:
            return await self._service.run_paragraph(notebook_id, paragraph_id)
        except ZeppelinGatewayError as error:
            self._raise_tool_error(error.tool_error)
        except Exception as error:
            self._raise_tool_error(
                unexpected_tool_error(error, operation=ToolOperation.RUN_PARAGRAPH)
            )

    async def get_paragraph_status(
        self, notebook_id: ZeppelinToolString, paragraph_id: ZeppelinToolString
    ) -> ParagraphStatusResult:
        """Inspect the normalized status of one paragraph."""

        try:
            return await self._service.get_paragraph_status(notebook_id, paragraph_id)
        except ZeppelinGatewayError as error:
            self._raise_tool_error(error.tool_error)
        except Exception as error:
            self._raise_tool_error(
                unexpected_tool_error(
                    error, operation=ToolOperation.GET_PARAGRAPH_STATUS
                )
            )

    async def get_paragraph_result(
        self, notebook_id: ZeppelinToolString, paragraph_id: ZeppelinToolString
    ) -> ParagraphResult:
        """Retrieve bounded paragraph outputs or safe failure details."""

        try:
            return await self._service.get_paragraph_result(notebook_id, paragraph_id)
        except ZeppelinGatewayError as error:
            self._raise_tool_error(error.tool_error)
        except Exception as error:
            self._raise_tool_error(
                unexpected_tool_error(
                    error, operation=ToolOperation.GET_PARAGRAPH_RESULT
                )
            )

    def _raise_tool_error(self, error: ToolError) -> NoReturn:
        payload = error.to_dict(secret_values=self._secret_values)
        serialized = json.dumps(
            payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        raise FastMCPToolError(serialized)
