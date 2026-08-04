"""Zeppelin application service tests with a fake gateway."""

from __future__ import annotations

import pytest

from mcp_stdio.core.errors import ErrorCategory
from mcp_stdio.plugins.zeppelin.gateway import ZeppelinGatewayError
from mcp_stdio.plugins.zeppelin.models import (
    OutputItem,
    OutputKind,
    ParagraphStatus,
    SafeErrorDetail,
)
from mcp_stdio.plugins.zeppelin.service import ZeppelinNotebookService


class FakeGateway:
    """Stub gateway returning canned results like the HTTP adapter would."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.create_result = "nb-1"
        self.add_result = "p-1"
        self.list_notebooks_result: tuple = ()
        self.run_status = ParagraphStatus.PENDING
        self.status_result = ParagraphStatus.FINISHED
        self.result_outputs: tuple[OutputItem, ...] = (
            OutputItem(kind=OutputKind.TEXT, text="ok"),
        )
        self.result_error: SafeErrorDetail | None = None
        self.result_truncated = False

    async def list_notebooks(self) -> tuple:
        self.calls.append(("list_notebooks",))
        return self.list_notebooks_result

    async def create_notebook(self, name: str) -> str:
        self.calls.append(("create_notebook", name))
        return self.create_result

    async def add_paragraph(self, notebook_id: str, title: str, body: str) -> str:
        self.calls.append(("add_paragraph", notebook_id, title, body))
        return self.add_result

    async def run_paragraph(self, notebook_id: str, paragraph_id: str) -> ParagraphStatus:
        self.calls.append(("run_paragraph", notebook_id, paragraph_id))
        return self.run_status

    async def get_paragraph_status(
        self, notebook_id: str, paragraph_id: str
    ) -> ParagraphStatus:
        self.calls.append(("get_paragraph_status", notebook_id, paragraph_id))
        return self.status_result

    async def get_paragraph_result(
        self, notebook_id: str, paragraph_id: str
    ) -> tuple[ParagraphStatus, tuple[OutputItem, ...], SafeErrorDetail | None, bool]:
        self.calls.append(("get_paragraph_result", notebook_id, paragraph_id))
        return self.status_result, self.result_outputs, self.result_error, self.result_truncated

    async def close(self) -> None:
        pass


def _service(
    *,
    allowed_interpreters: tuple[str, ...] = ("spark",),
    max_notebook_name_chars: int = 256,
    max_paragraph_title_chars: int = 256,
    max_paragraph_body_bytes: int = 65_536,
    max_opaque_id_chars: int = 512,
    sql_write_allowed_databases: tuple[str, ...] = ("tmp_dc_ep",),
    sh_allowed_commands: tuple[str, ...] = (),
) -> tuple[ZeppelinNotebookService, FakeGateway]:
    gateway = FakeGateway()
    service = ZeppelinNotebookService(
        gateway=gateway,
        allowed_interpreters=allowed_interpreters,
        max_notebook_name_chars=max_notebook_name_chars,
        max_paragraph_title_chars=max_paragraph_title_chars,
        max_paragraph_body_bytes=max_paragraph_body_bytes,
        max_opaque_id_chars=max_opaque_id_chars,
        sql_write_allowed_databases=sql_write_allowed_databases,
        sh_allowed_commands=sh_allowed_commands,
    )
    return service, gateway


async def test_create_notebook_returns_result() -> None:
    service, gateway = _service()
    result = await service.create_notebook("  my-note  ")
    assert result.notebook_id == "nb-1"
    assert result.name == "  my-note  "
    assert gateway.calls == [("create_notebook", "  my-note  ")]


async def test_create_notebook_rejects_empty_name() -> None:
    service, _ = _service()
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await service.create_notebook("   ")
    assert exc_info.value.tool_error.category == ErrorCategory.INVALID_INPUT


async def test_add_paragraph_rejects_non_allowlisted_interpreter_before_network() -> None:
    service, gateway = _service(allowed_interpreters=("spark",))
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await service.add_paragraph("nb-1", "title", "%sh\nbody")
    assert exc_info.value.tool_error.category == ErrorCategory.INVALID_INPUT
    assert gateway.calls == []


async def test_add_paragraph_rejects_body_without_shebang_before_network() -> None:
    service, gateway = _service(allowed_interpreters=("spark",))
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await service.add_paragraph("nb-1", "title", "SELECT 1")
    assert exc_info.value.tool_error.category == ErrorCategory.INVALID_INPUT
    assert gateway.calls == []


async def test_add_paragraph_returns_result() -> None:
    service, gateway = _service()
    result = await service.add_paragraph("nb-1", "title", "%spark\nbody")
    assert result.notebook_id == "nb-1"
    assert result.paragraph_id == "p-1"
    assert result.title == "title"
    assert result.interpreter == "spark"


async def test_add_paragraph_sends_body_verbatim() -> None:
    service, gateway = _service()
    body = "%spark\nval x = 1"
    await service.add_paragraph("nb-1", "title", body)
    assert gateway.calls == [("add_paragraph", "nb-1", "title", body)]


async def test_add_paragraph_allows_sql_write_to_approved_database() -> None:
    service, gateway = _service(allowed_interpreters=("spark.sql",))
    result = await service.add_paragraph(
        "nb-1", "title", "%spark.sql\nINSERT INTO tmp_dc_ep.my_table VALUES (1)"
    )
    assert result.paragraph_id == "p-1"
    assert result.interpreter == "spark.sql"
    assert any(call[0] == "add_paragraph" for call in gateway.calls)


async def test_add_paragraph_rejects_sql_write_to_non_approved_database_before_network() -> None:
    service, gateway = _service(allowed_interpreters=("spark.sql",))
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await service.add_paragraph(
            "nb-1", "title", "%spark.sql\nINSERT INTO other_db.my_table VALUES (1)"
        )
    assert exc_info.value.tool_error.category == ErrorCategory.INVALID_INPUT
    assert gateway.calls == []


async def test_add_paragraph_allows_sql_read_against_any_database() -> None:
    service, gateway = _service(allowed_interpreters=("spark.sql",))
    result = await service.add_paragraph(
        "nb-1", "title", "%spark.sql\nSELECT * FROM any_db.t"
    )
    assert result.paragraph_id == "p-1"


async def test_add_paragraph_rejects_unqualified_sql_write_before_network() -> None:
    service, gateway = _service(allowed_interpreters=("spark.sql",))
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await service.add_paragraph(
            "nb-1", "title", "%spark.sql\nINSERT INTO my_table VALUES (1)"
        )
    assert exc_info.value.tool_error.category == ErrorCategory.INVALID_INPUT
    assert gateway.calls == []


async def test_add_paragraph_rejects_non_allowlisted_sh_command_before_network() -> None:
    service, gateway = _service(
        allowed_interpreters=("sh",), sh_allowed_commands=("echo", "cat")
    )
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await service.add_paragraph("nb-1", "title", "%sh\nrm -rf /tmp/x")
    assert exc_info.value.tool_error.category == ErrorCategory.INVALID_INPUT
    assert gateway.calls == []


async def test_add_paragraph_allows_allowlisted_sh_command() -> None:
    service, gateway = _service(
        allowed_interpreters=("sh",), sh_allowed_commands=("echo", "cat")
    )
    result = await service.add_paragraph("nb-1", "title", "%sh\necho hello")
    assert result.paragraph_id == "p-1"
    assert result.interpreter == "sh"
    assert any(call[0] == "add_paragraph" for call in gateway.calls)


async def test_add_paragraph_denies_all_sh_commands_by_default() -> None:
    service, gateway = _service(allowed_interpreters=("sh",))
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await service.add_paragraph("nb-1", "title", "%sh\necho hello")
    assert exc_info.value.tool_error.category == ErrorCategory.INVALID_INPUT
    assert gateway.calls == []


async def test_run_paragraph_returns_status() -> None:
    service, _ = _service()
    result = await service.run_paragraph("nb-1", "p-1")
    assert result.status is ParagraphStatus.PENDING


async def test_get_paragraph_status_returns_status() -> None:
    service, _ = _service()
    result = await service.get_paragraph_status("nb-1", "p-1")
    assert result.status is ParagraphStatus.FINISHED


async def test_get_paragraph_result_returns_result() -> None:
    service, _ = _service()
    result = await service.get_paragraph_result("nb-1", "p-1")
    assert result.status is ParagraphStatus.FINISHED
    assert len(result.outputs) == 1
    assert result.error is None
    assert result.truncated is False


async def test_get_paragraph_result_error_preserves_failure_outputs_and_exception() -> None:
    from mcp_stdio.plugins.zeppelin.models import OutputItem, OutputKind, SafeErrorDetail

    service, gateway = _service()
    gateway.status_result = ParagraphStatus.ERROR
    gateway.result_outputs = (OutputItem(kind=OutputKind.TEXT, text="Traceback: boom"),)
    gateway.result_error = SafeErrorDetail(message="upstream exception")
    result = await service.get_paragraph_result("nb-1", "p-1")
    assert result.status is ParagraphStatus.ERROR
    assert len(result.outputs) == 1
    assert "Traceback: boom" in result.outputs[0].text
    assert result.error is not None
    assert result.error.message == "upstream exception"


async def test_get_paragraph_result_error_with_empty_exception_keeps_outputs_and_summary() -> None:
    from mcp_stdio.plugins.zeppelin.models import OutputItem, OutputKind

    service, gateway = _service()
    gateway.status_result = ParagraphStatus.ERROR
    gateway.result_outputs = (OutputItem(kind=OutputKind.TEXT, text="ExitValue: 1"),)
    gateway.result_error = None
    result = await service.get_paragraph_result("nb-1", "p-1")
    assert result.status is ParagraphStatus.ERROR
    assert len(result.outputs) == 1
    assert result.outputs[0].text == "ExitValue: 1"
    assert result.error is not None
    assert result.error.message  # non-empty summary, not the upstream empty exception


async def test_list_notebooks_returns_tree() -> None:
    from mcp_stdio.plugins.zeppelin.models import NotebookTreeNode

    service, gateway = _service()
    gateway.list_notebooks_result = (
        NotebookTreeNode(name="team", path="/team", notebook_id=None, children=(
            NotebookTreeNode(name="note-a", path="/team/note-a", notebook_id="nb-1", children=()),
        )),
    )
    result = await service.list_notebooks()
    assert len(result.nodes) == 1
    assert result.nodes[0].name == "team"
    assert result.nodes[0].children[0].notebook_id == "nb-1"
