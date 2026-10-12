"""Zeppelin application service tests with a fake gateway."""

from __future__ import annotations

import inspect
import json

import pytest
from pydantic import ValidationError

from mcp_stdio.core.errors import (
    ErrorCategory,
    ToolError,
    ToolOperation,
    safe_error_identifiers,
)
from mcp_stdio.plugins.zeppelin.gateway import ZeppelinGatewayError
from mcp_stdio.plugins.zeppelin.models import (
    CancelParagraphResult,
    InterpreterBinding,
    InterpreterBindingRecord,
    InterpreterBindingsResult,
    NotebookTreeNode,
    OutputItem,
    OutputKind,
    ParagraphStatus,
    RestartInterpreterResult,
    SafeErrorDetail,
)
from mcp_stdio.plugins.zeppelin.safety import build_default_safety_hook
from mcp_stdio.plugins.zeppelin.service import ZeppelinNotebookService


class FakeGateway:
    """Stub gateway returning canned results like the HTTP adapter would."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.create_result = "nb-1"
        self.add_result = "p-1"
        self.list_notebooks_result: tuple[NotebookTreeNode, ...] = ()
        self.run_status = ParagraphStatus.PENDING
        self.status_result = ParagraphStatus.FINISHED
        self.result_outputs: tuple[OutputItem, ...] = (
            OutputItem(kind=OutputKind.TEXT, text="ok"),
        )
        self.result_error: SafeErrorDetail | None = None
        self.result_truncated = False
        self.binding_result: tuple[InterpreterBindingRecord, ...] = ()
        self.binding_error: ZeppelinGatewayError | None = None

    async def list_notebooks(self) -> tuple[NotebookTreeNode, ...]:
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

    async def cancel_paragraph(self, notebook_id: str, paragraph_id: str) -> CancelParagraphResult:
        self.calls.append(("cancel_paragraph", notebook_id, paragraph_id))
        return CancelParagraphResult(notebook_id=notebook_id, paragraph_id=paragraph_id)

    async def get_interpreter_bindings(
        self, notebook_id: str
    ) -> tuple[InterpreterBindingRecord, ...]:
        self.calls.append(("get_interpreter_bindings", notebook_id))
        if self.binding_error is not None:
            raise self.binding_error
        return self.binding_result

    async def restart_interpreter(
        self, setting_id: str, notebook_id: str | None = None
    ) -> RestartInterpreterResult:
        self.calls.append(("restart_interpreter", setting_id, notebook_id))
        return RestartInterpreterResult(
            setting_id=setting_id,
            name=setting_id,
            group=setting_id,
            status="READY",
        )

    async def close(self) -> None:
        pass


def _service(
    *,
    allowed_interpreters: tuple[str, ...] = ("spark",),
    max_notebook_name_chars: int = 256,
    max_paragraph_title_chars: int = 256,
    max_paragraph_body_bytes: int = 65_536,
    max_opaque_id_chars: int = 512,
    max_result_bytes: int = 65_536,
    sql_write_allowed_databases: tuple[str, ...] = ("tmp_dc_ep",),
    sh_allowed_commands: tuple[str, ...] = (),
    sql_forbidden_keywords: tuple[str, ...] = ("DROP", "TRUNCATE"),
    restartable_interpreter_settings: tuple[str, ...] = (),
) -> tuple[ZeppelinNotebookService, FakeGateway]:
    gateway = FakeGateway()
    safety_hook = build_default_safety_hook(
        allowed_interpreters=allowed_interpreters,
        sql_forbidden_keywords=sql_forbidden_keywords,
        sql_write_allowed_databases=sql_write_allowed_databases,
        sh_allowed_commands=sh_allowed_commands,
    )
    service = ZeppelinNotebookService(
        gateway=gateway,
        safety_hook=safety_hook,
        restartable_interpreter_settings=restartable_interpreter_settings,
        max_notebook_name_chars=max_notebook_name_chars,
        max_paragraph_title_chars=max_paragraph_title_chars,
        max_paragraph_body_bytes=max_paragraph_body_bytes,
        max_opaque_id_chars=max_opaque_id_chars,
        max_result_bytes=max_result_bytes,
    )
    return service, gateway


def _compact_result_bytes(result: InterpreterBindingsResult) -> bytes:
    return json.dumps(
        result.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def test_gateway_contract_has_discovery_and_optional_notebook_restart_signatures() -> None:
    from mcp_stdio.plugins.zeppelin.gateway import ZeppelinGateway

    for contract in (ZeppelinGateway, FakeGateway):
        discovery = inspect.signature(contract.get_interpreter_bindings)
        assert list(discovery.parameters) == ["self", "notebook_id"]
        assert discovery.parameters["notebook_id"].default is inspect.Parameter.empty

        restart = inspect.signature(contract.restart_interpreter)
        assert list(restart.parameters) == ["self", "setting_id", "notebook_id"]
        assert restart.parameters["setting_id"].default is inspect.Parameter.empty
        assert restart.parameters["notebook_id"].default is None


@pytest.mark.parametrize("notebook_id", [None, "", "bad\ncontrol", "12345"])
async def test_get_interpreter_bindings_rejects_invalid_id_before_network(
    notebook_id: object,
) -> None:
    service, gateway = _service(max_opaque_id_chars=4)

    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await service.get_interpreter_bindings(notebook_id)

    assert exc_info.value.tool_error.category is ErrorCategory.INVALID_INPUT
    assert exc_info.value.tool_error.operation is ToolOperation.GET_INTERPRETER_BINDINGS
    assert exc_info.value.tool_error.retryable is False
    assert gateway.calls == []


async def test_get_interpreter_bindings_preserves_numeric_and_reserved_id() -> None:
    service, gateway = _service(max_opaque_id_chars=64)
    notebook_id = "2AY6/path?x=1#frag"

    result = await service.get_interpreter_bindings(notebook_id)

    assert result.notebook_id == notebook_id
    assert gateway.calls == [("get_interpreter_bindings", notebook_id)]


async def test_get_interpreter_bindings_needs_no_execution_or_restart_permission() -> None:
    service, gateway = _service(
        allowed_interpreters=(),
        restartable_interpreter_settings=(),
    )
    gateway.binding_result = (
        InterpreterBindingRecord(
            setting_id="spark_prod",
            name="production spark",
            interpreters=("spark", "sql"),
            selected=True,
        ),
        InterpreterBindingRecord(
            setting_id="sh",
            name="shell",
            interpreters=("sh",),
            selected=False,
        ),
    )

    result = await service.get_interpreter_bindings("note-1")

    assert tuple(binding.setting_id for binding in result.bindings) == (
        "spark_prod",
        "sh",
    )
    assert tuple(binding.restart_allowed for binding in result.bindings) == (False, False)
    assert gateway.calls == [("get_interpreter_bindings", "note-1")]


async def test_get_interpreter_bindings_decorates_exact_case_sensitive_id_membership() -> None:
    service, gateway = _service(
        allowed_interpreters=(),
        restartable_interpreter_settings=("Allowed-ID", "2/id?x=1"),
    )
    gateway.binding_result = (
        InterpreterBindingRecord(
            setting_id="Allowed-ID",
            name="unrelated",
            interpreters=("other",),
            selected=False,
        ),
        InterpreterBindingRecord(
            setting_id="allowed-id",
            name="Allowed-ID",
            interpreters=("Allowed-ID",),
            selected=True,
        ),
        InterpreterBindingRecord(
            setting_id="2/id?x=1",
            name="opaque",
            interpreters=(),
            selected=False,
        ),
    )

    result = await service.get_interpreter_bindings("note-1")

    assert tuple(binding.restart_allowed for binding in result.bindings) == (
        True,
        False,
        True,
    )


async def test_get_interpreter_bindings_preserves_empty_upstream_result() -> None:
    service, gateway = _service()

    result = await service.get_interpreter_bindings("note-empty")

    assert result == InterpreterBindingsResult(notebook_id="note-empty", bindings=())
    assert gateway.calls == [("get_interpreter_bindings", "note-empty")]


async def test_get_interpreter_bindings_preserves_gateway_error_metadata() -> None:
    service, gateway = _service()
    upstream_error = ToolError.create(
        category=ErrorCategory.CONNECTION_FAILED,
        operation=ToolOperation.GET_INTERPRETER_BINDINGS,
        retryable=True,
        identifiers={"notebook_id": "note-1"},
    )
    gateway.binding_error = ZeppelinGatewayError(upstream_error)

    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await service.get_interpreter_bindings("note-1")

    assert exc_info.value.tool_error is upstream_error


async def test_get_interpreter_bindings_omits_long_id_from_gateway_error() -> None:
    notebook_id = "n" * 257
    service, gateway = _service(max_opaque_id_chars=512)
    upstream_error = ToolError.create(
        category=ErrorCategory.TIMEOUT,
        operation=ToolOperation.GET_INTERPRETER_BINDINGS,
        retryable=True,
        identifiers=safe_error_identifiers(
            ToolOperation.GET_INTERPRETER_BINDINGS,
            {"notebook_id": notebook_id},
        ),
    )
    gateway.binding_error = ZeppelinGatewayError(upstream_error)

    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await service.get_interpreter_bindings(notebook_id)

    error = exc_info.value.tool_error
    assert error.operation is ToolOperation.GET_INTERPRETER_BINDINGS
    assert error.category is ErrorCategory.TIMEOUT
    assert error.retryable is True
    assert dict(error.identifiers) == {}


async def test_get_interpreter_bindings_accepts_exact_compact_utf8_result_size() -> None:
    record = InterpreterBindingRecord(
        setting_id="spark-数",
        name="计算",
        interpreters=("spark",),
        selected=True,
    )
    expected = InterpreterBindingsResult(
        notebook_id="note-数",
        bindings=(
            InterpreterBinding(
                **record.model_dump(),
                restart_allowed=True,
            ),
        ),
    )
    exact_bytes = len(_compact_result_bytes(expected))
    service, gateway = _service(
        restartable_interpreter_settings=(record.setting_id,),
        max_result_bytes=exact_bytes,
    )
    gateway.binding_result = (record,)

    result = await service.get_interpreter_bindings(expected.notebook_id)

    assert result == expected
    assert len(_compact_result_bytes(result)) == exact_bytes


async def test_get_interpreter_bindings_rejects_complete_result_one_byte_over_limit() -> None:
    record = InterpreterBindingRecord(
        setting_id="spark-数",
        name="计算",
        interpreters=("spark",),
        selected=True,
    )
    expected = InterpreterBindingsResult(
        notebook_id="note-数",
        bindings=(
            InterpreterBinding(
                **record.model_dump(),
                restart_allowed=False,
            ),
        ),
    )
    exact_bytes = len(_compact_result_bytes(expected))
    service, gateway = _service(max_result_bytes=exact_bytes - 1)
    gateway.binding_result = (record,)

    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await service.get_interpreter_bindings(expected.notebook_id)

    error = exc_info.value.tool_error
    assert error.category is ErrorCategory.UNEXPECTED_RESPONSE
    assert error.operation is ToolOperation.GET_INTERPRETER_BINDINGS
    assert error.retryable is False
    assert dict(error.identifiers) == {"notebook_id": expected.notebook_id}
    assert gateway.calls == [("get_interpreter_bindings", expected.notebook_id)]


async def test_get_interpreter_bindings_public_result_is_exact_immutable_json() -> None:
    service, gateway = _service(restartable_interpreter_settings=("spark_prod",))
    gateway.binding_result = (
        InterpreterBindingRecord(
            setting_id="spark_prod",
            name="production",
            interpreters=("spark", "sql"),
            selected=True,
        ),
    )

    result = await service.get_interpreter_bindings("note-1")
    public = result.model_dump(mode="json")

    assert set(public) == {"notebook_id", "bindings"}
    assert set(public["bindings"][0]) == {
        "setting_id",
        "name",
        "interpreters",
        "selected",
        "restart_allowed",
    }
    assert {
        "ticket",
        "principal",
        "roles",
        "cookie",
        "headers",
        "transport",
    }.isdisjoint(public["bindings"][0])
    assert json.loads(_compact_result_bytes(result)) == public
    with pytest.raises(ValidationError):
        result.__setattr__("notebook_id", "changed")
    with pytest.raises(ValidationError):
        result.bindings[0].__setattr__("selected", False)


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
    service, _gateway = _service()
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
    service, _gateway = _service(allowed_interpreters=("spark.sql",))
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


async def test_add_paragraph_rejects_forbidden_drop_on_approved_database() -> None:
    service, gateway = _service(allowed_interpreters=("spark.sql",))
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await service.add_paragraph(
            "nb-1", "title", "%spark.sql\nDROP TABLE tmp_dc_ep.my_table"
        )
    assert exc_info.value.tool_error.category == ErrorCategory.INVALID_INPUT
    assert gateway.calls == []


async def test_add_paragraph_rejects_forbidden_truncate_on_approved_database() -> None:
    service, gateway = _service(allowed_interpreters=("spark.sql",))
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await service.add_paragraph(
            "nb-1", "title", "%spark.sql\nTRUNCATE TABLE tmp_dc_ep.my_table"
        )
    assert exc_info.value.tool_error.category == ErrorCategory.INVALID_INPUT
    assert gateway.calls == []


async def test_add_paragraph_allows_create_on_approved_database() -> None:
    service, _gateway = _service(allowed_interpreters=("spark.sql",))
    result = await service.add_paragraph(
        "nb-1", "title", "%spark.sql\nCREATE TABLE tmp_dc_ep.my_table (id int)"
    )
    assert result.paragraph_id == "p-1"


async def test_add_paragraph_allows_alter_on_approved_database() -> None:
    service, _gateway = _service(allowed_interpreters=("spark.sql",))
    result = await service.add_paragraph(
        "nb-1", "title", "%spark.sql\nALTER TABLE tmp_dc_ep.my_table ADD COLUMNS (x int)"
    )
    assert result.paragraph_id == "p-1"


async def test_add_paragraph_explanation_names_forbidden_keyword() -> None:
    service, gateway = _service(allowed_interpreters=("spark.sql",))
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await service.add_paragraph(
            "nb-1", "title", "%spark.sql\nDROP TABLE tmp_dc_ep.my_table"
        )
    assert exc_info.value.tool_error.explanation is not None
    assert "DROP" in exc_info.value.tool_error.explanation
    assert gateway.calls == []


async def test_add_paragraph_explanation_names_rejected_database() -> None:
    service, gateway = _service(allowed_interpreters=("spark.sql",))
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await service.add_paragraph(
            "nb-1", "title", "%spark.sql\nINSERT INTO other_db.t VALUES (1)"
        )
    assert exc_info.value.tool_error.explanation is not None
    assert "other_db" in exc_info.value.tool_error.explanation
    assert gateway.calls == []


async def test_add_paragraph_explanation_names_rejected_interpreter() -> None:
    service, gateway = _service(allowed_interpreters=("spark.sql",))
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await service.add_paragraph("nb-1", "title", "%sh\necho hi")
    assert exc_info.value.tool_error.explanation is not None
    assert "sh" in exc_info.value.tool_error.explanation
    assert gateway.calls == []


async def test_add_paragraph_explains_missing_shebang() -> None:
    service, gateway = _service(allowed_interpreters=("spark",))
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await service.add_paragraph("nb-1", "title", "SELECT 1")
    assert exc_info.value.tool_error.explanation is not None
    assert "shebang" in exc_info.value.tool_error.explanation
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


async def test_add_paragraph_rejects_spark_sql_write_to_non_approved_db() -> None:
    service, gateway = _service()
    body = (
        '%spark\n'
        'spark.sql("INSERT OVERWRITE TABLE dwd_dc_ep.x SELECT 1")'
    )
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await service.add_paragraph("nb-1", "title", body)
    assert exc_info.value.tool_error.category == ErrorCategory.INVALID_INPUT
    assert gateway.calls == []


async def test_add_paragraph_rejects_spark_sql_forbidden_drop() -> None:
    service, gateway = _service()
    body = '%spark\nspark.sql("DROP TABLE dwd_dc_ep.x")'
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await service.add_paragraph("nb-1", "title", body)
    assert exc_info.value.tool_error.category == ErrorCategory.INVALID_INPUT
    assert exc_info.value.tool_error.explanation is not None
    assert "DROP" in exc_info.value.tool_error.explanation
    assert gateway.calls == []


async def test_add_paragraph_explains_embedded_sql_write_target_rejection() -> None:
    service, _gateway = _service()
    body = (
        '%spark\n'
        'spark.sql("INSERT OVERWRITE TABLE dwd_dc_ep.x SELECT 1")'
    )
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await service.add_paragraph("nb-1", "title", body)
    assert exc_info.value.tool_error.explanation is not None
    assert "dwd_dc_ep" in exc_info.value.tool_error.explanation


async def test_add_paragraph_allows_spark_sql_read() -> None:
    service, gateway = _service()
    body = '%spark\nspark.sql("SELECT * FROM tmp_dc_ep.t")'
    result = await service.add_paragraph("nb-1", "title", body)
    assert result.paragraph_id == "p-1"
    assert result.interpreter == "spark"
    assert any(call[0] == "add_paragraph" for call in gateway.calls)


async def test_add_paragraph_allows_spark_code_without_sql_calls() -> None:
    service, gateway = _service()
    body = '%spark\nval df = spark.read.parquet("/path")'
    result = await service.add_paragraph("nb-1", "title", body)
    assert result.paragraph_id == "p-1"
    assert any(call[0] == "add_paragraph" for call in gateway.calls)


async def test_add_paragraph_allows_spark_sql_write_to_approved_database() -> None:
    service, gateway = _service()
    body = '%spark\nspark.sql("INSERT INTO tmp_dc_ep.t VALUES (1)")'
    result = await service.add_paragraph("nb-1", "title", body)
    assert result.paragraph_id == "p-1"
    assert any(call[0] == "add_paragraph" for call in gateway.calls)


async def test_add_paragraph_rejects_spark_sql_triple_quoted_write_to_non_approved() -> None:
    service, gateway = _service()
    body = (
        '%spark\n'
        'spark.sql("""INSERT OVERWRITE TABLE dwd_dc_ep.x\nSELECT 1""")'
    )
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await service.add_paragraph("nb-1", "title", body)
    assert exc_info.value.tool_error.category == ErrorCategory.INVALID_INPUT
    assert gateway.calls == []


async def test_add_paragraph_allows_multiple_safe_spark_sql_calls() -> None:
    service, gateway = _service()
    body = (
        '%spark\n'
        'spark.sql("SELECT 1")\n'
        'spark.sql("SELECT * FROM tmp_dc_ep.t")'
    )
    result = await service.add_paragraph("nb-1", "title", body)
    assert result.paragraph_id == "p-1"
    assert any(call[0] == "add_paragraph" for call in gateway.calls)


async def test_restart_interpreter_rejects_non_allowlisted_before_network() -> None:
    service, gateway = _service()
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await service.restart_interpreter("spark")
    assert exc_info.value.tool_error.category == ErrorCategory.INVALID_INPUT
    assert gateway.calls == []


async def test_restart_interpreter_rejects_malformed_setting_id() -> None:
    service, gateway = _service(restartable_interpreter_settings=("spark",))
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await service.restart_interpreter("bad setting!")
    assert exc_info.value.tool_error.category == ErrorCategory.INVALID_INPUT
    assert gateway.calls == []


async def test_restart_interpreter_allowlisted_calls_gateway() -> None:
    service, gateway = _service(restartable_interpreter_settings=("spark",))
    result = await service.restart_interpreter("spark")
    assert isinstance(result, RestartInterpreterResult)
    assert result.setting_id == "spark"
    assert result.status == "READY"
    assert any(call[0] == "restart_interpreter" for call in gateway.calls)


async def test_restart_interpreter_returns_result_from_gateway() -> None:
    service, _gateway = _service(restartable_interpreter_settings=("spark", "sh"))
    result = await service.restart_interpreter("sh")
    assert result.setting_id == "sh"
    assert result.group == "sh"



async def test_cancel_paragraph_returns_result() -> None:
    service, gateway = _service()
    result = await service.cancel_paragraph("nb-1", "p-1")
    assert isinstance(result, CancelParagraphResult)
    assert result.notebook_id == "nb-1"
    assert result.paragraph_id == "p-1"
    assert any(call[0] == "cancel_paragraph" for call in gateway.calls)


async def test_cancel_paragraph_rejects_malformed_ids_before_network() -> None:
    service, gateway = _service()
    with pytest.raises(ZeppelinGatewayError) as exc_info:
        await service.cancel_paragraph("bad\x00id", "p-1")
    assert exc_info.value.tool_error.category == ErrorCategory.INVALID_INPUT
    assert gateway.calls == []


@pytest.mark.parametrize("setting_id", ["2AY6GV7Q3", "2/a%2F?x=# 中", "x" * 300, ".", ".."])
@pytest.mark.parametrize("notebook_id", [None, "2/n%2F?x=# 中"])
async def test_restart_preserves_opaque_ids_and_optional_context(
    setting_id: str, notebook_id: str | None,
) -> None:
    service, gateway = _service(restartable_interpreter_settings=(setting_id,))
    result = await service.restart_interpreter(setting_id, notebook_id)
    assert result.setting_id == setting_id
    assert gateway.calls == [("restart_interpreter", setting_id, notebook_id)]


async def test_restart_omitted_and_null_context_are_identical() -> None:
    service, gateway = _service(restartable_interpreter_settings=("spark",))
    assert await service.restart_interpreter("spark") == await service.restart_interpreter(
        "spark", None,
    )
    assert gateway.calls == [("restart_interpreter", "spark", None)] * 2


async def test_restart_legacy_accepts_numeric_leading_opaque_setting() -> None:
    service, gateway = _service(restartable_interpreter_settings=("2/id?x",))
    assert (await service.restart_interpreter("2/id?x")).setting_id == "2/id?x"
    assert gateway.calls == [("restart_interpreter", "2/id?x", None)]


@pytest.mark.parametrize("invalid", ["", 123, True, "bad\x00id", "bad\x7fid", "x" * 9])
@pytest.mark.parametrize("field", ["setting", "notebook"])
async def test_restart_validates_both_ids_before_any_gateway_call(
    invalid: object, field: str,
) -> None:
    service, gateway = _service(
        restartable_interpreter_settings=("spark",), max_opaque_id_chars=8,
    )
    setting_id = invalid if field == "setting" else "spark"
    notebook_id = invalid if field == "notebook" else "note"
    with pytest.raises(ZeppelinGatewayError) as failure:
        await service.restart_interpreter(setting_id, notebook_id)
    error = failure.value.tool_error
    assert error.category == ErrorCategory.INVALID_INPUT
    assert error.operation == ToolOperation.RESTART_INTERPRETER
    assert not error.retryable
    assert gateway.calls == []


@pytest.mark.parametrize("setting_id", ["Spark", "spark ", "spark.sql", "s" * 300])
@pytest.mark.parametrize("notebook_id", [None, "note"])
async def test_restart_allowlist_is_exact_and_error_identifiers_are_safe(
    setting_id: str, notebook_id: str | None,
) -> None:
    service, gateway = _service(restartable_interpreter_settings=("spark",))
    with pytest.raises(ZeppelinGatewayError) as failure:
        await service.restart_interpreter(setting_id, notebook_id)
    error = failure.value.tool_error
    assert error.category == ErrorCategory.INVALID_INPUT
    assert error.identifiers == safe_error_identifiers(
        ToolOperation.RESTART_INTERPRETER,
        {"setting_id": setting_id, "notebook_id": notebook_id},
    )
    assert setting_id not in (error.explanation or "")
    assert gateway.calls == []
