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
    CancelParagraphResult,
    CreateNotebookResult,
    InterpreterBindingsResult,
    NotebookTreeResult,
    ParagraphResult,
    ParagraphStatusResult,
    RestartInterpreterResult,
    RunParagraphResult,
)
from mcp_stdio.plugins.zeppelin.service import ZeppelinNotebookService

ZeppelinToolString = Annotated[object, WithJsonSchema({"type": "string"})]
ZeppelinToolNullableString = Annotated[
    object,
    WithJsonSchema({"anyOf": [{"type": "string"}, {"type": "null"}]}),
]


class ZeppelinToolAdapter:
    """Translate typed inbound calls to the Zeppelin application service."""

    def __init__(
        self,
        *,
        service: ZeppelinNotebookService,
        secret_values: Iterable[str],
    ) -> None:
        self._service = service
        self._secret_values = tuple(value for value in secret_values if value)

    def register_tools(self, registrar: ToolRegistrar) -> None:
        """Register exactly the nine approved Zeppelin notebook tools."""

        registrar.add_tool(self.list_notebooks, name="list_notebooks")
        registrar.add_tool(self.create_notebook, name="create_notebook")
        registrar.add_tool(self.add_paragraph, name="add_paragraph")
        registrar.add_tool(self.run_paragraph, name="run_paragraph")
        registrar.add_tool(self.get_paragraph_status, name="get_paragraph_status")
        registrar.add_tool(self.get_paragraph_result, name="get_paragraph_result")
        registrar.add_tool(
            self.get_interpreter_bindings,
            name="get_interpreter_bindings",
        )
        registrar.add_tool(self.restart_interpreter, name="restart_interpreter")
        registrar.add_tool(self.cancel_paragraph, name="cancel_paragraph")

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
        body: ZeppelinToolString,
    ) -> AddParagraphResult:
        """Add an allowlisted paragraph to an existing notebook."""

        try:
            return await self._service.add_paragraph(notebook_id, title, body)
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
                unexpected_tool_error(error, operation=ToolOperation.GET_PARAGRAPH_STATUS)
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
                unexpected_tool_error(error, operation=ToolOperation.GET_PARAGRAPH_RESULT)
            )

    async def get_interpreter_bindings(
        self, notebook_id: ZeppelinToolString,
    ) -> InterpreterBindingsResult:
        """Discover exact setting IDs for a readable notebook without execution/restart.

        Explicitly select a binding with selected=true and restart_allowed=true,
        then restart with that exact ID and the same notebook_id; never guess IDs
        from names or paragraph prefixes. restart_allowed is local policy, not
        upstream authorization or health. Execution and restart allowlists are
        independent; discovery requires neither permission.
        """

        try:
            return await self._service.get_interpreter_bindings(notebook_id)
        except ZeppelinGatewayError as error:
            self._raise_tool_error(error.tool_error)
        except Exception as error:
            self._raise_tool_error(
                unexpected_tool_error(
                    error,
                    operation=ToolOperation.GET_INTERPRETER_BINDINGS,
                )
            )

    async def restart_interpreter(
        self,
        setting_id: ZeppelinToolString,
        notebook_id: ZeppelinToolNullableString = None,
    ) -> RestartInterpreterResult:
        """Restart an exact allowlisted setting after explicit binding selection.

        Use get_interpreter_bindings first and pass the same notebook_id with a
        selected, restart_allowed setting_id. Execution and restart permissions
        are independent. Omitted/null notebook_id preserves legacy setting-wide
        scope. Notebook context does not isolate shared interpreter processes.
        Never guess IDs, drop context as fallback, retry a restart automatically,
        treat restart as a general retry, or automatically re-execute a paragraph.
        The four-field result acknowledges reported state, not verified health.
        """

        try:
            return await self._service.restart_interpreter(setting_id, notebook_id)
        except ZeppelinGatewayError as error:
            self._raise_tool_error(error.tool_error)
        except Exception as error:
            self._raise_tool_error(
                unexpected_tool_error(error, operation=ToolOperation.RESTART_INTERPRETER)
            )

    async def cancel_paragraph(
        self, notebook_id: ZeppelinToolString, paragraph_id: ZeppelinToolString
    ) -> CancelParagraphResult:
        """Cancel a running Zeppelin paragraph."""

        try:
            return await self._service.cancel_paragraph(notebook_id, paragraph_id)
        except ZeppelinGatewayError as error:
            self._raise_tool_error(error.tool_error)
        except Exception as error:
            self._raise_tool_error(
                unexpected_tool_error(error, operation=ToolOperation.CANCEL_PARAGRAPH)
            )

    def _raise_tool_error(self, error: ToolError) -> NoReturn:
        payload = error.to_dict(secret_values=self._secret_values)
        serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        raise FastMCPToolError(serialized)
