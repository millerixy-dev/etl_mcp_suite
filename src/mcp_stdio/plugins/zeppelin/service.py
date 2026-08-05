"""MCP- and httpx-independent Zeppelin notebook application service."""

from __future__ import annotations

from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation
from mcp_stdio.plugins.zeppelin.gateway import ZeppelinGateway, ZeppelinGatewayError
from mcp_stdio.plugins.zeppelin.models import (
    AddParagraphResult,
    CancelParagraphResult,
    CreateNotebookResult,
    NotebookTreeResult,
    ParagraphResult,
    ParagraphStatus,
    ParagraphStatusResult,
    RestartInterpreterResult,
    RunParagraphResult,
    SafeErrorDetail,
    parse_paragraph_interpreter,
    validate_interpreter_name,
    validate_notebook_name,
    validate_opaque_id,
    validate_paragraph_body,
    validate_paragraph_title,
)
from mcp_stdio.plugins.zeppelin.safety import ParagraphSafetyHook


def _invalid_input(
    operation: ToolOperation, explanation: str | None = None
) -> ZeppelinGatewayError:
    return ZeppelinGatewayError(
        ToolError.create(
            category=ErrorCategory.INVALID_INPUT,
            operation=operation,
            retryable=False,
            explanation=explanation,
        )
    )


class ZeppelinNotebookService:
    """Coordinate validated Zeppelin notebook use cases."""

    def __init__(
        self,
        *,
        gateway: ZeppelinGateway,
        safety_hook: ParagraphSafetyHook,
        restartable_interpreter_settings: tuple[str, ...],
        max_notebook_name_chars: int,
        max_paragraph_title_chars: int,
        max_paragraph_body_bytes: int,
        max_opaque_id_chars: int,
    ) -> None:
        self._gateway = gateway
        self._safety_hook = safety_hook
        self._restartable = frozenset(restartable_interpreter_settings)
        self._max_nb = max_notebook_name_chars
        self._max_title = max_paragraph_title_chars
        self._max_body = max_paragraph_body_bytes
        self._max_id = max_opaque_id_chars

    async def list_notebooks(self) -> NotebookTreeResult:
        nodes = await self._gateway.list_notebooks()
        return NotebookTreeResult(nodes=nodes)

    async def restart_interpreter(self, setting_id: object) -> RestartInterpreterResult:
        try:
            sid = validate_interpreter_name(setting_id)
        except ValueError as exc:
            raise _invalid_input(
                ToolOperation.RESTART_INTERPRETER, explanation=str(exc)
            ) from None
        if sid not in self._restartable:
            raise _invalid_input(
                ToolOperation.RESTART_INTERPRETER,
                explanation=f"interpreter setting '{sid}' is not in the restart allowlist",
            ) from None
        return await self._gateway.restart_interpreter(sid)

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
        body: object,
    ) -> AddParagraphResult:
        try:
            nb = validate_opaque_id(notebook_id, max_chars=self._max_id)
            ttl = validate_paragraph_title(title, max_chars=self._max_title)
            bdy = validate_paragraph_body(body, max_bytes=self._max_body)
            intr = parse_paragraph_interpreter(bdy)
        except ValueError as exc:
            raise _invalid_input(ToolOperation.ADD_PARAGRAPH, explanation=str(exc)) from None
        if intr is None:
            raise _invalid_input(
                ToolOperation.ADD_PARAGRAPH,
                explanation="paragraph body has no interpreter shebang",
            )
        try:
            self._safety_hook.enforce(intr, bdy)
        except ValueError as exc:
            raise _invalid_input(ToolOperation.ADD_PARAGRAPH, explanation=str(exc)) from None
        paragraph_id = await self._gateway.add_paragraph(nb, ttl, bdy)
        return AddParagraphResult(
            notebook_id=nb,
            paragraph_id=paragraph_id,
            title=ttl,
            interpreter=intr,
        )

    async def run_paragraph(self, notebook_id: object, paragraph_id: object) -> RunParagraphResult:
        try:
            nb = validate_opaque_id(notebook_id, max_chars=self._max_id)
            pid = validate_opaque_id(paragraph_id, max_chars=self._max_id)
        except ValueError:
            raise _invalid_input(ToolOperation.RUN_PARAGRAPH) from None
        status = await self._gateway.run_paragraph(nb, pid)
        return RunParagraphResult(notebook_id=nb, paragraph_id=pid, status=status)

    async def cancel_paragraph(
        self, notebook_id: object, paragraph_id: object
    ) -> CancelParagraphResult:
        try:
            nb = validate_opaque_id(notebook_id, max_chars=self._max_id)
            pid = validate_opaque_id(paragraph_id, max_chars=self._max_id)
        except ValueError as exc:
            raise _invalid_input(
                ToolOperation.CANCEL_PARAGRAPH, explanation=str(exc)
            ) from None
        await self._gateway.cancel_paragraph(nb, pid)
        return CancelParagraphResult(notebook_id=nb, paragraph_id=pid)

    async def get_paragraph_status(
        self, notebook_id: object, paragraph_id: object
    ) -> ParagraphStatusResult:
        try:
            nb = validate_opaque_id(notebook_id, max_chars=self._max_id)
            pid = validate_opaque_id(paragraph_id, max_chars=self._max_id)
        except ValueError:
            raise _invalid_input(ToolOperation.GET_PARAGRAPH_STATUS) from None
        status = await self._gateway.get_paragraph_status(nb, pid)
        return ParagraphStatusResult(notebook_id=nb, paragraph_id=pid, status=status)

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
            safe_error = (
                error
                if (error is not None and error.message)
                else SafeErrorDetail(message="paragraph execution failed")
            )
            return ParagraphResult(
                notebook_id=nb,
                paragraph_id=pid,
                status=status,
                outputs=outputs,
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
