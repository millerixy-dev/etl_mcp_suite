"""Tests for stable, secret-safe tool error mapping."""

from __future__ import annotations

import inspect
import json
import logging
from collections.abc import Iterator, Mapping
from typing import cast
from uuid import UUID

import pytest


class ExplodingIdentifiers(Mapping[str, str]):
    def __init__(self, sentinel: str) -> None:
        self._sentinel = sentinel

    def __getitem__(self, key: str) -> str:
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        raise RuntimeError(self._sentinel)

    def __len__(self) -> int:
        return 1


def test_error_categories_are_exactly_the_stable_public_set() -> None:
    from mcp_stdio.core.errors import ErrorCategory

    assert {category.value for category in ErrorCategory} == {
        "CONFIG_ERROR",
        "INVALID_INPUT",
        "AUTHENTICATION_FAILED",
        "PERMISSION_DENIED",
        "NOT_FOUND",
        "CONNECTION_FAILED",
        "TIMEOUT",
        "UPSTREAM_ERROR",
        "UNEXPECTED_RESPONSE",
    }


def test_tool_operations_are_closed_to_v1_tools_plus_internal_fallback() -> None:
    from mcp_stdio.core.errors import ToolOperation

    public_operations = {operation.value for operation in ToolOperation} - {
        ToolOperation.RUNTIME.value
    }

    assert public_operations == {
        "list_databases",
        "list_notebooks",
        "list_tables",
        "get_table_schema",
        "create_notebook",
        "add_paragraph",
        "run_paragraph",
        "get_paragraph_status",
        "get_paragraph_result",
        "get_server_status",
        "restart_interpreter",
        "cancel_paragraph",
        "list_objects",
        "get_object",
        "search_objects",
        "start_workflow",
        "get_task_log",
        "extract_log_links",
    }


def test_restart_interpreter_operation_allows_setting_id_identifier() -> None:
    from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation

    error = ToolError.create(
        category=ErrorCategory.UPSTREAM_ERROR,
        operation=ToolOperation.RESTART_INTERPRETER,
        retryable=False,
        identifiers={"setting_id": "spark"},
    )
    assert error.to_dict(secret_values=())["identifiers"] == {"setting_id": "spark"}


def test_cancel_paragraph_operation_allows_notebook_and_paragraph_identifiers() -> None:
    from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation

    error = ToolError.create(
        category=ErrorCategory.UPSTREAM_ERROR,
        operation=ToolOperation.CANCEL_PARAGRAPH,
        retryable=False,
        identifiers={"notebook_id": "nb-1", "paragraph_id": "p-1"},
    )
    result = error.to_dict(secret_values=())["identifiers"]
    assert result == {"notebook_id": "nb-1", "paragraph_id": "p-1"}
    assert result == {"notebook_id": "nb-1", "paragraph_id": "p-1"}


def test_tool_error_serializes_only_the_safe_structured_contract() -> None:
    from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation

    error = ToolError.create(
        category=ErrorCategory.NOT_FOUND,
        operation=ToolOperation.GET_TABLE_SCHEMA,
        retryable=False,
        identifiers={"database": "analytics", "table": "daily_sales"},
    )

    payload = error.to_dict(secret_values=())

    assert payload == {
        "category": "NOT_FOUND",
        "operation": "get_table_schema",
        "message": "The requested resource was not found.",
        "retryable": False,
        "identifiers": {"database": "analytics", "table": "daily_sales"},
        "correlation_id": error.correlation_id,
    }
    UUID(error.correlation_id)
    assert json.loads(json.dumps(payload)) == payload


def test_tool_error_generates_a_new_correlation_id_per_failure() -> None:
    from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation

    first = ToolError.create(
        category=ErrorCategory.TIMEOUT,
        operation=ToolOperation.GET_PARAGRAPH_STATUS,
        retryable=True,
    )
    second = ToolError.create(
        category=ErrorCategory.TIMEOUT,
        operation=ToolOperation.GET_PARAGRAPH_STATUS,
        retryable=True,
    )

    assert first.correlation_id != second.correlation_id


@pytest.mark.parametrize(
    ("category", "message"),
    [
        ("CONFIG_ERROR", "Configuration is invalid."),
        ("INVALID_INPUT", "The request input is invalid."),
        ("AUTHENTICATION_FAILED", "Authentication failed."),
        ("PERMISSION_DENIED", "Permission was denied."),
        ("NOT_FOUND", "The requested resource was not found."),
        ("CONNECTION_FAILED", "Could not connect to the upstream service."),
        ("TIMEOUT", "The upstream operation timed out."),
        ("UPSTREAM_ERROR", "The upstream operation failed."),
        ("UNEXPECTED_RESPONSE", "The upstream response was not understood."),
    ],
)
def test_tool_error_message_is_fixed_by_category(category: str, message: str) -> None:
    from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation

    error = ToolError.create(
        category=ErrorCategory(category),
        operation=ToolOperation.GET_SERVER_STATUS,
        retryable=False,
    )

    assert error.message == message


def test_tool_error_includes_concise_explanation_when_provided() -> None:
    from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation

    error = ToolError.create(
        category=ErrorCategory.INVALID_INPUT,
        operation=ToolOperation.ADD_PARAGRAPH,
        retryable=False,
        explanation="sql write target database 'other_db' is not allowlisted",
    )

    payload = error.to_dict(secret_values=())

    assert payload["explanation"] == "sql write target database 'other_db' is not allowlisted"
    assert payload["message"] == "The request input is invalid."


def test_tool_error_omits_explanation_when_absent() -> None:
    from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation

    error = ToolError.create(
        category=ErrorCategory.INVALID_INPUT,
        operation=ToolOperation.ADD_PARAGRAPH,
        retryable=False,
    )

    payload = error.to_dict(secret_values=())

    assert "explanation" not in payload


def test_tool_error_explanation_is_none_by_default() -> None:
    from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation

    error = ToolError.create(
        category=ErrorCategory.INVALID_INPUT,
        operation=ToolOperation.ADD_PARAGRAPH,
        retryable=False,
    )

    assert error.explanation is None


def test_tool_error_explanation_is_a_constructor_field() -> None:
    from mcp_stdio.core.errors import ToolError

    assert "explanation" in inspect.signature(ToolError).parameters


def test_tool_error_omits_explanation_containing_a_known_secret() -> None:
    from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation

    secret = "explanation-secret-sentinel"
    error = ToolError.create(
        category=ErrorCategory.INVALID_INPUT,
        operation=ToolOperation.ADD_PARAGRAPH,
        retryable=False,
        explanation=f"detail {secret} detail",
    )

    payload = error.to_dict(secret_values=(secret,))

    assert "explanation" not in payload
    assert secret not in json.dumps(payload)


def test_direct_construction_cannot_inject_message_or_correlation_id() -> None:
    from mcp_stdio.core.errors import ToolError

    constructor_fields = inspect.signature(ToolError).parameters

    assert "message" not in constructor_fields
    assert "correlation_id" not in constructor_fields


def test_tool_error_rejects_arbitrary_operation_string() -> None:
    from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation

    with pytest.raises(ValueError):
        ToolError.create(
            category=ErrorCategory.INVALID_INPUT,
            operation=cast(ToolOperation, "arbitrary_operation"),
            retryable=False,
        )


@pytest.mark.parametrize(
    ("operation_name", "identifiers"),
    [
        ("list_tables", {"table": "not-allowed-for-list-tables"}),
        ("get_table_schema", {"password": "identifier-password-sentinel"}),
        ("add_paragraph", {"notebook_id": "unsafe\ncontrol"}),
        ("add_paragraph", {"notebook_id": "x" * 257}),
    ],
)
def test_tool_error_rejects_disallowed_or_unsafe_identifiers(
    operation_name: str,
    identifiers: dict[str, str],
) -> None:
    from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation

    with pytest.raises(ValueError):
        ToolError.create(
            category=ErrorCategory.INVALID_INPUT,
            operation=ToolOperation(operation_name),
            retryable=False,
            identifiers=identifiers,
        )


def test_tool_error_accepts_bounded_opaque_identifier_characters() -> None:
    from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation

    opaque_id = "notebook+opaque==%2Fsegment"
    error = ToolError.create(
        category=ErrorCategory.NOT_FOUND,
        operation=ToolOperation.ADD_PARAGRAPH,
        retryable=False,
        identifiers={"notebook_id": opaque_id},
    )

    assert error.to_dict(secret_values=())["identifiers"] == {"notebook_id": opaque_id}


def test_tool_error_serialization_omits_identifier_containing_known_secret() -> None:
    from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation

    secret = "known-identifier-secret-sentinel"
    error = ToolError.create(
        category=ErrorCategory.NOT_FOUND,
        operation=ToolOperation.ADD_PARAGRAPH,
        retryable=False,
        identifiers={"notebook_id": f"opaque-prefix-{secret}-suffix"},
    )

    payload = error.to_dict(secret_values=(secret,))

    assert payload["identifiers"] == {}
    assert secret not in json.dumps(payload)


def test_unexpected_mapper_does_not_accept_a_caller_logger() -> None:
    from mcp_stdio.core.errors import unexpected_tool_error

    assert "logger" not in inspect.signature(unexpected_tool_error).parameters


def test_unexpected_exception_is_generic_and_logged_with_correlation_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_stdio.core.errors import ToolOperation, unexpected_tool_error
    from mcp_stdio.core.logging import configure_logging

    secret = "unexpected-exception-unknown-sentinel"
    configure_logging()
    try:
        raise RuntimeError(f"raw upstream failure without structural label {secret}")
    except RuntimeError as error:
        mapped = unexpected_tool_error(
            error,
            operation=ToolOperation.RUN_PARAGRAPH,
            identifiers={
                "notebook_id": "safe-notebook-id",
                "paragraph_id": "safe-paragraph-id",
            },
        )

    captured = capsys.readouterr()
    payload_text = json.dumps(mapped.to_dict(secret_values=(secret,)))

    assert mapped.category.value == "UPSTREAM_ERROR"
    assert mapped.message == "The upstream operation failed."
    assert mapped.retryable is False
    assert mapped.identifiers == {
        "notebook_id": "safe-notebook-id",
        "paragraph_id": "safe-paragraph-id",
    }
    assert mapped.correlation_id in captured.err
    assert "unexpected exception during run_paragraph" in captured.err
    assert secret not in payload_text
    assert "raw upstream failure" not in payload_text
    assert secret not in captured.err
    assert "RuntimeError" not in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""
    logging.getLogger("mcp_stdio").handlers.clear()


@pytest.mark.parametrize(
    ("operation", "identifiers", "sentinel"),
    [
        ("hostile_operation", {}, "hostile-operation-secret-sentinel"),
        (
            "add_paragraph",
            {"notebook_id": "unsafe\nidentifier-secret-sentinel"},
            "identifier-secret-sentinel",
        ),
        (
            "add_paragraph",
            ExplodingIdentifiers("mapping-runtime-secret-sentinel"),
            "mapping-runtime-secret-sentinel",
        ),
    ],
)
def test_unexpected_mapper_falls_back_safely_for_hostile_runtime_inputs(
    operation: str,
    identifiers: object,
    sentinel: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_stdio.core.errors import ToolOperation, unexpected_tool_error
    from mcp_stdio.core.logging import configure_logging

    configure_logging()

    mapped = unexpected_tool_error(
        RuntimeError(f"raw exception {sentinel}"),
        operation=cast(ToolOperation, operation),
        identifiers=cast(Mapping[str, str], identifiers),
    )
    captured = capsys.readouterr()
    payload = mapped.to_dict(secret_values=(sentinel,))
    payload_text = json.dumps(payload)

    assert mapped.operation is ToolOperation.RUNTIME
    assert payload["identifiers"] == {}
    assert mapped.correlation_id in captured.err
    assert sentinel not in captured.err
    assert sentinel not in payload_text
    assert captured.out == ""
    logging.getLogger("mcp_stdio").handlers.clear()


@pytest.mark.parametrize(
    "operation_name",
    [
        "list_objects",
        "get_object",
        "search_objects",
        "start_workflow",
        "get_task_log",
        "extract_log_links",
    ],
)
def test_scheduling_operation_creates_safe_tool_error(operation_name: str) -> None:
    from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation

    error = ToolError.create(
        category=ErrorCategory.UPSTREAM_ERROR,
        operation=ToolOperation(operation_name),
        retryable=False,
        identifiers={},
    )
    assert error.operation.value == operation_name
    assert error.to_dict(secret_values=())["identifiers"] == {}
