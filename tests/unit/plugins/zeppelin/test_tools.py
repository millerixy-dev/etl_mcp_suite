"""Zeppelin inbound tool contracts, strict inputs, and safe-error tests."""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Awaitable, Callable
from typing import cast

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError as FastMCPToolError
from mcp.types import TextContent

from mcp_stdio.contracts.plugin import ToolHandler
from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation
from mcp_stdio.core.logging import configure_logging
from mcp_stdio.plugins.zeppelin.gateway import ZeppelinGateway, ZeppelinGatewayError
from mcp_stdio.plugins.zeppelin.models import (
    InterpreterBinding,
    InterpreterBindingRecord,
    InterpreterBindingsResult,
    RestartInterpreterResult,
)
from mcp_stdio.plugins.zeppelin.safety import build_default_safety_hook
from mcp_stdio.plugins.zeppelin.service import ZeppelinNotebookService
from mcp_stdio.plugins.zeppelin.tools import ZeppelinToolAdapter

TOOL_NAMES = (
    "list_notebooks",
    "create_notebook",
    "add_paragraph",
    "run_paragraph",
    "get_paragraph_status",
    "get_paragraph_result",
    "get_interpreter_bindings",
    "restart_interpreter",
    "cancel_paragraph",
)


class RecordingRegistrar:
    def __init__(self) -> None:
        self.tools: list[tuple[ToolHandler, str | None]] = []

    def add_tool(self, fn: ToolHandler, name: str | None = None) -> None:
        self.tools.append((fn, name))


class FakeZeppelinService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.failures: dict[str, Exception] = {}

    async def get_interpreter_bindings(
        self, notebook_id: object,
    ) -> InterpreterBindingsResult:
        self.calls.append(("get_interpreter_bindings", notebook_id))
        self._raise_failure("get_interpreter_bindings")
        assert isinstance(notebook_id, str)
        return InterpreterBindingsResult(
            notebook_id=notebook_id,
            bindings=(
                InterpreterBinding(
                    setting_id="spark-prod",
                    name="Spark Production",
                    interpreters=("spark", "sql"),
                    selected=True,
                    restart_allowed=True,
                ),
            ),
        )

    async def restart_interpreter(
        self, setting_id: object, notebook_id: object = None,
    ) -> RestartInterpreterResult:
        self.calls.append(("restart_interpreter", setting_id, notebook_id))
        self._raise_failure("restart_interpreter")
        assert isinstance(setting_id, str)
        return RestartInterpreterResult(
            setting_id=setting_id,
            name="Spark Production",
            group="spark",
            status="READY",
        )

    def _raise_failure(self, operation: str) -> None:
        failure = self.failures.get(operation)
        if failure is not None:
            raise failure


class RecordingGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    async def get_interpreter_bindings(
        self, notebook_id: str,
    ) -> tuple[InterpreterBindingRecord, ...]:
        self.calls.append(("get_interpreter_bindings", notebook_id))
        return ()

    async def restart_interpreter(
        self, setting_id: str, notebook_id: str | None = None,
    ) -> RestartInterpreterResult:
        self.calls.append(("restart_interpreter", setting_id, notebook_id))
        return RestartInterpreterResult(
            setting_id=setting_id,
            name="Spark Production",
            group="spark",
            status="READY",
        )


def tool_adapter(
    service: FakeZeppelinService,
    *,
    secret_values: tuple[str, ...] = (),
) -> ZeppelinToolAdapter:
    return ZeppelinToolAdapter(
        service=cast(ZeppelinNotebookService, service),
        secret_values=secret_values,
    )


def registered_handlers(
    adapter: ZeppelinToolAdapter,
) -> dict[str, Callable[..., Awaitable[object]]]:
    registrar = RecordingRegistrar()
    adapter.register_tools(registrar)
    return {
        cast(str, name): cast(Callable[..., Awaitable[object]], handler)
        for handler, name in registrar.tools
    }


def real_tool_server(
    gateway: RecordingGateway,
    *,
    secret_values: tuple[str, ...] = (),
) -> FastMCP:
    service = ZeppelinNotebookService(
        gateway=cast(ZeppelinGateway, gateway),
        safety_hook=build_default_safety_hook(
            allowed_interpreters=(),
            sql_forbidden_keywords=("DROP", "TRUNCATE"),
            sql_write_allowed_databases=("tmp_dc_ep",),
            sh_allowed_commands=(),
        ),
        restartable_interpreter_settings=("spark-prod",),
        max_notebook_name_chars=256,
        max_paragraph_title_chars=256,
        max_paragraph_body_bytes=65_536,
        max_opaque_id_chars=512,
        max_result_bytes=65_536,
    )
    server = FastMCP("zeppelin-real-boundary")
    ZeppelinToolAdapter(service=service, secret_values=secret_values).register_tools(server)
    return server


def safe_error_payload(error: FastMCPToolError) -> dict[str, object]:
    text = str(error)
    payload_start = text.find("{")
    assert payload_start >= 0
    payload = json.loads(text[payload_start:])
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


def public_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        return {
            *(key for key in mapping if isinstance(key, str)),
            *(key for item in mapping.values() for key in public_keys(item)),
        }
    if isinstance(value, list):
        return {key for item in cast(list[object], value) for key in public_keys(item)}
    return set()


async def test_registers_exact_nine_tools_with_narrow_public_signatures() -> None:
    handlers = registered_handlers(tool_adapter(FakeZeppelinService()))

    assert tuple(handlers) == TOOL_NAMES
    assert tuple(inspect.signature(handlers["get_interpreter_bindings"]).parameters) == (
        "notebook_id",
    )
    assert tuple(inspect.signature(handlers["restart_interpreter"]).parameters) == (
        "setting_id",
        "notebook_id",
    )
    assert inspect.signature(handlers["restart_interpreter"]).parameters[
        "notebook_id"
    ].default is None
    assert not {
        "set_interpreter_bindings",
        "list_interpreter_settings",
        "ticket",
        "cookie",
        "roles",
    }.intersection(handlers)


async def test_discovery_and_restart_delegate_once_and_preserve_notebook_scope() -> None:
    service = FakeZeppelinService()
    handlers = registered_handlers(tool_adapter(service))

    discovery = await handlers["get_interpreter_bindings"]("note/2?x")
    omitted = await handlers["restart_interpreter"]("spark-prod")
    explicit_null = await handlers["restart_interpreter"]("spark-prod", None)
    contextual = await handlers["restart_interpreter"]("spark-prod", "note/2?x")

    assert isinstance(discovery, InterpreterBindingsResult)
    assert isinstance(omitted, RestartInterpreterResult)
    assert explicit_null == omitted == contextual
    assert service.calls == [
        ("get_interpreter_bindings", "note/2?x"),
        ("restart_interpreter", "spark-prod", None),
        ("restart_interpreter", "spark-prod", None),
        ("restart_interpreter", "spark-prod", "note/2?x"),
    ]


async def test_fastmcp_schemas_preserve_existing_inputs_and_add_nullable_restart_scope() -> None:
    server = FastMCP("zeppelin-contract")
    tool_adapter(FakeZeppelinService()).register_tools(server)

    tools = {tool.name: tool for tool in await server.list_tools()}

    assert tuple(tools) == TOOL_NAMES
    expected_properties: dict[str, dict[str, dict[str, object]]] = {
        "list_notebooks": {},
        "create_notebook": {"name": {"title": "Name", "type": "string"}},
        "add_paragraph": {
            "notebook_id": {"title": "Notebook Id", "type": "string"},
            "title": {"title": "Title", "type": "string"},
            "body": {"title": "Body", "type": "string"},
        },
        "run_paragraph": {
            "notebook_id": {"title": "Notebook Id", "type": "string"},
            "paragraph_id": {"title": "Paragraph Id", "type": "string"},
        },
        "get_paragraph_status": {
            "notebook_id": {"title": "Notebook Id", "type": "string"},
            "paragraph_id": {"title": "Paragraph Id", "type": "string"},
        },
        "get_paragraph_result": {
            "notebook_id": {"title": "Notebook Id", "type": "string"},
            "paragraph_id": {"title": "Paragraph Id", "type": "string"},
        },
        "get_interpreter_bindings": {
            "notebook_id": {"title": "Notebook Id", "type": "string"},
        },
        "restart_interpreter": {
            "setting_id": {"title": "Setting Id", "type": "string"},
            "notebook_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Notebook Id",
            },
        },
        "cancel_paragraph": {
            "notebook_id": {"title": "Notebook Id", "type": "string"},
            "paragraph_id": {"title": "Paragraph Id", "type": "string"},
        },
    }
    expected_required = {
        "list_notebooks": [],
        "create_notebook": ["name"],
        "add_paragraph": ["notebook_id", "title", "body"],
        "run_paragraph": ["notebook_id", "paragraph_id"],
        "get_paragraph_status": ["notebook_id", "paragraph_id"],
        "get_paragraph_result": ["notebook_id", "paragraph_id"],
        "get_interpreter_bindings": ["notebook_id"],
        "restart_interpreter": ["setting_id"],
        "cancel_paragraph": ["notebook_id", "paragraph_id"],
    }
    for name, tool in tools.items():
        expected_schema: dict[str, object] = {
            "properties": expected_properties[name],
            "title": f"{name}Arguments",
            "type": "object",
        }
        if expected_required[name]:
            expected_schema["required"] = expected_required[name]
        assert tool.inputSchema == expected_schema

    assert tools["get_interpreter_bindings"].outputSchema == (
        InterpreterBindingsResult.model_json_schema()
    )
    assert tools["restart_interpreter"].outputSchema == (
        RestartInterpreterResult.model_json_schema()
    )


async def test_fastmcp_calls_return_exact_public_structured_results() -> None:
    server = FastMCP("zeppelin-structured-contract")
    tool_adapter(FakeZeppelinService()).register_tools(server)

    expectations: list[tuple[str, dict[str, object], dict[str, object]]] = [
        (
            "get_interpreter_bindings",
            {"notebook_id": "note-1"},
            {
                "notebook_id": "note-1",
                "bindings": [
                    {
                        "setting_id": "spark-prod",
                        "name": "Spark Production",
                        "interpreters": ["spark", "sql"],
                        "selected": True,
                        "restart_allowed": True,
                    },
                ],
            },
        ),
        (
            "restart_interpreter",
            {"setting_id": "spark-prod", "notebook_id": "note-1"},
            {
                "setting_id": "spark-prod",
                "name": "Spark Production",
                "group": "spark",
                "status": "READY",
            },
        ),
    ]

    for name, arguments, expected in expectations:
        raw_result = await server.call_tool(name, arguments)
        assert isinstance(raw_result, tuple)
        content, structured = cast(tuple[list[TextContent], dict[str, object]], raw_result)
        assert structured == expected
        if name == "get_interpreter_bindings":
            assert not {"ticket", "cookie", "roles", "transport", "group", "status"}.intersection(
                public_keys(structured)
            )
        assert len(content) == 1
        assert json.loads(content[0].text) == expected



@pytest.mark.parametrize(
    ("operation", "arguments", "identifiers"),
    [
        (
            "get_interpreter_bindings",
            ("credential-sentinel",),
            {"notebook_id": "credential-sentinel"},
        ),
        (
            "restart_interpreter",
            ("spark-prod", "credential-sentinel"),
            {"setting_id": "spark-prod", "notebook_id": "credential-sentinel"},
        ),
    ],
)
async def test_gateway_errors_are_stable_filtered_and_non_emitting(
    operation: str,
    arguments: tuple[object, ...],
    identifiers: dict[str, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "credential-sentinel"
    service = FakeZeppelinService()
    tool_operation = ToolOperation(operation)
    domain_error = ToolError.create(
        category=ErrorCategory.TIMEOUT,
        operation=tool_operation,
        retryable=operation == "get_interpreter_bindings",
        identifiers=identifiers,
        explanation=f"safe explanation excluding {secret}",
    )
    service.failures[operation] = ZeppelinGatewayError(domain_error)
    handler = registered_handlers(
        tool_adapter(service, secret_values=(secret,))
    )[operation]

    with pytest.raises(FastMCPToolError) as captured:
        await handler(*arguments)

    payload = safe_error_payload(captured.value)
    assert payload["category"] == "TIMEOUT"
    assert payload["operation"] == operation
    assert payload["retryable"] is (operation == "get_interpreter_bindings")
    assert payload["identifiers"] == (
        {"setting_id": "spark-prod"} if operation == "restart_interpreter" else {}
    )
    assert "explanation" not in payload
    assert secret not in str(captured.value)
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    ("operation", "arguments"),
    [
        ("get_interpreter_bindings", ("note-1",)),
        ("restart_interpreter", ("spark-prod", "note-1")),
    ],
)
async def test_unexpected_errors_are_generic_safe_and_emit_only_safe_diagnostics(
    operation: str,
    arguments: tuple[object, ...],
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    sentinel = "raw-exception-sentinel"
    configure_logging(secret_values=(sentinel,))
    service = FakeZeppelinService()
    service.failures[operation] = RuntimeError(f"raw backend failure {sentinel}")
    handler = registered_handlers(
        tool_adapter(service, secret_values=(sentinel,))
    )[operation]

    with pytest.raises(FastMCPToolError) as captured:
        await handler(*arguments)

    payload = safe_error_payload(captured.value)
    assert payload["category"] == "UPSTREAM_ERROR"
    assert payload["operation"] == operation
    assert payload["retryable"] is False
    assert payload["identifiers"] == {}
    assert sentinel not in str(captured.value)
    assert sentinel not in caplog.text
    output = capsys.readouterr()
    assert output.out == ""
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} ERROR mcp_stdio\.errors "
        + re.escape(
            f"unexpected exception during {operation} correlation_id={payload['correlation_id']}"
        )
        + r"\n",
        output.err,
    )
    assert sentinel not in output.err
    assert "raw backend failure" not in output.err
    assert "raw backend failure" not in caplog.text


@pytest.mark.parametrize(
    "notebook_id",
    [1, 0, False, {"ticket": "wire-secret-sentinel"}, None],
)
async def test_fastmcp_discovery_rejects_non_strings_before_gateway(
    notebook_id: object,
) -> None:
    secret = "wire-secret-sentinel"
    gateway = RecordingGateway()
    server = real_tool_server(gateway, secret_values=(secret,))

    with pytest.raises(FastMCPToolError) as captured:
        await server.call_tool("get_interpreter_bindings", {"notebook_id": notebook_id})

    payload = safe_error_payload(captured.value)
    assert payload["category"] == "INVALID_INPUT"
    assert payload["operation"] == "get_interpreter_bindings"
    assert payload["identifiers"] == {}
    assert gateway.calls == []
    assert secret not in str(captured.value)


@pytest.mark.parametrize(
    "arguments",
    [
        {"setting_id": 1},
        {"setting_id": "spark-prod", "notebook_id": 1},
        {"setting_id": "spark-prod", "notebook_id": False},
        {"setting_id": "spark-prod", "notebook_id": ""},
        {
            "setting_id": "spark-prod",
            "notebook_id": {"cookie": "wire-secret-sentinel"},
        },
    ],
)
async def test_fastmcp_restart_rejects_non_string_non_null_inputs_before_gateway(
    arguments: dict[str, object],
) -> None:
    secret = "wire-secret-sentinel"
    gateway = RecordingGateway()
    server = real_tool_server(gateway, secret_values=(secret,))

    with pytest.raises(FastMCPToolError) as captured:
        await server.call_tool("restart_interpreter", arguments)

    payload = safe_error_payload(captured.value)
    assert payload["category"] == "INVALID_INPUT"
    assert payload["operation"] == "restart_interpreter"
    assert gateway.calls == []
    assert secret not in str(captured.value)


async def test_fastmcp_restart_omission_null_and_value_preserve_scope() -> None:
    gateway = RecordingGateway()
    server = real_tool_server(gateway)

    await server.call_tool("restart_interpreter", {"setting_id": "spark-prod"})
    await server.call_tool(
        "restart_interpreter", {"setting_id": "spark-prod", "notebook_id": None}
    )
    await server.call_tool(
        "restart_interpreter",
        {"setting_id": "spark-prod", "notebook_id": "note-1"},
    )

    assert gateway.calls == [
        ("restart_interpreter", "spark-prod", None),
        ("restart_interpreter", "spark-prod", None),
        ("restart_interpreter", "spark-prod", "note-1"),
    ]


def test_recovery_tool_descriptions_explain_exact_selection_and_scope() -> None:
    discovery = ZeppelinToolAdapter.get_interpreter_bindings.__doc__ or ""
    restart = ZeppelinToolAdapter.restart_interpreter.__doc__ or ""
    for marker in ("exact", "selected", "restart_allowed", "independent"):
        assert marker in discovery
    for marker in (
        "get_interpreter_bindings", "notebook_id", "null", "setting-wide",
        "shared", "fallback", "retry", "paragraph",
    ):
        assert marker in restart
