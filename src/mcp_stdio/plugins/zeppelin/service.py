"""MCP- and httpx-independent Zeppelin notebook application service."""

from __future__ import annotations

from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation
from mcp_stdio.plugins.zeppelin.gateway import ZeppelinGateway, ZeppelinGatewayError
from mcp_stdio.plugins.zeppelin.models import (
    AddParagraphResult,
    CreateNotebookResult,
    NotebookTreeResult,
    ParagraphResult,
    ParagraphStatus,
    ParagraphStatusResult,
    RunParagraphResult,
    SafeErrorDetail,
    validate_interpreter_name,
    validate_notebook_name,
    validate_opaque_id,
    validate_paragraph_body,
    validate_paragraph_title,
)


def _invalid_input(operation: ToolOperation) -> ZeppelinGatewayError:
    return ZeppelinGatewayError(
        ToolError.create(
            category=ErrorCategory.INVALID_INPUT,
            operation=operation,
            retryable=False,
        )
    )


class ZeppelinNotebookService:
    """Coordinate validated Zeppelin notebook use cases."""

    def __init__(
        self,
        *,
        gateway: ZeppelinGateway,
        allowed_interpreters: tuple[str, ...],
        max_notebook_name_chars: int,
        max_paragraph_title_chars: int,
        max_paragraph_body_bytes: int,
        max_opaque_id_chars: int,
    ) -> None:
        self._gateway = gateway
        self._allowed = frozenset(allowed_interpreters)
        self._max_nb = max_notebook_name_chars
        self._max_title = max_paragraph_title_chars
        self._max_body = max_paragraph_body_bytes
        self._max_id = max_opaque_id_chars

    async def list_notebooks(self) -> NotebookTreeResult:
        nodes = await self._gateway.list_notebooks()
        return NotebookTreeResult(nodes=nodes)

    async def create_notebook(self, name: object) -> CreateNotebookResult:
        try:
            validated = validate_notebook_name(name, max_chars=self._max_nb)
        except ValueError:
            raise _invalid_input(ToolOperation.CREATE_NOTEBOOK) from None
        notebook_id = await self._gateway.create_notebook(validated)
        return CreateNotebookResult(notebook_id=notebook_id, name=validated)

    async def add_paragraph(
        self,
        notebook_id: object,
        title: object,
        interpreter: object,
        body: object,
    ) -> AddParagraphResult:
        try:
            nb = validate_opaque_id(notebook_id, max_chars=self._max_id)
            ttl = validate_paragraph_title(title, max_chars=self._max_title)
            intr = validate_interpreter_name(interpreter)
            bdy = validate_paragraph_body(body, max_bytes=self._max_body)
        except ValueError:
            raise _invalid_input(ToolOperation.ADD_PARAGRAPH) from None
        if intr not in self._allowed:
            raise _invalid_input(ToolOperation.ADD_PARAGRAPH)
        paragraph_id = await self._gateway.add_paragraph(nb, ttl, intr, bdy)
        return AddParagraphResult(
            notebook_id=nb,
            paragraph_id=paragraph_id,
            title=ttl,
            interpreter=intr,
        )

    async def run_paragraph(
        self, notebook_id: object, paragraph_id: object
    ) -> RunParagraphResult:
        try:
            nb = validate_opaque_id(notebook_id, max_chars=self._max_id)
            pid = validate_opaque_id(paragraph_id, max_chars=self._max_id)
        except ValueError:
            raise _invalid_input(ToolOperation.RUN_PARAGRAPH) from None
        status = await self._gateway.run_paragraph(nb, pid)
        return RunParagraphResult(
            notebook_id=nb, paragraph_id=pid, status=status
        )

    async def get_paragraph_status(
        self, notebook_id: object, paragraph_id: object
    ) -> ParagraphStatusResult:
        try:
            nb = validate_opaque_id(notebook_id, max_chars=self._max_id)
            pid = validate_opaque_id(paragraph_id, max_chars=self._max_id)
        except ValueError:
            raise _invalid_input(ToolOperation.GET_PARAGRAPH_STATUS) from None
        status = await self._gateway.get_paragraph_status(nb, pid)
        return ParagraphStatusResult(
            notebook_id=nb, paragraph_id=pid, status=status
        )

    async def get_paragraph_result(
        self, notebook_id: object, paragraph_id: object
    ) -> ParagraphResult:
        try:
            nb = validate_opaque_id(notebook_id, max_chars=self._max_id)
            pid = validate_opaque_id(paragraph_id, max_chars=self._max_id)
        except ValueError:
            raise _invalid_input(ToolOperation.GET_PARAGRAPH_RESULT) from None
        status, outputs, error, truncated = await self._gateway.get_paragraph_result(nb, pid)
        if status == ParagraphStatus.ERROR:
            safe_error: SafeErrorDetail | None = error or SafeErrorDetail(
                message="paragraph execution failed"
            )
            return ParagraphResult(
                notebook_id=nb,
                paragraph_id=pid,
                status=status,
                outputs=(),
                error=safe_error,
                truncated=truncated,
            )
        if status != ParagraphStatus.FINISHED:
            raise _invalid_input(ToolOperation.GET_PARAGRAPH_RESULT)
        return ParagraphResult(
            notebook_id=nb,
            paragraph_id=pid,
            status=status,
            outputs=outputs,
            error=None,
            truncated=truncated,
        )
