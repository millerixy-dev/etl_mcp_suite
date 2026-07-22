"""Tests for stable, secret-safe tool error mapping."""

from __future__ import annotations

import inspect
import json
import logging
from uuid import UUID

import pytest


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


def test_tool_error_serializes_only_the_safe_structured_contract() -> None:
    from mcp_stdio.core.errors import ErrorCategory, ToolError

    error = ToolError.create(
        category=ErrorCategory.NOT_FOUND,
        operation="get_table_schema",
        retryable=False,
        identifiers={"database": "analytics", "table": "daily_sales"},
    )

    payload = error.to_dict()

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
    from mcp_stdio.core.errors import ErrorCategory, ToolError

    first = ToolError.create(
        category=ErrorCategory.TIMEOUT,
        operation="get_paragraph_status",
        retryable=True,
    )
    second = ToolError.create(
        category=ErrorCategory.TIMEOUT,
        operation="get_paragraph_status",
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
    from mcp_stdio.core.errors import ErrorCategory, ToolError

    error = ToolError.create(
        category=ErrorCategory(category),
        operation="get_server_status",
        retryable=False,
    )

    assert error.message == message


def test_direct_construction_cannot_inject_message_or_correlation_id() -> None:
    from mcp_stdio.core.errors import ToolError

    constructor_fields = inspect.signature(ToolError).parameters

    assert "message" not in constructor_fields
    assert "correlation_id" not in constructor_fields


@pytest.mark.parametrize(
    ("operation", "identifiers"),
    [
        ("Get Table", {}),
        ("get-table", {}),
        ("x" * 65, {}),
        ("get_table_schema", {"password": "identifier-password-sentinel"}),
        ("get_table_schema", {"table": "multi word identifier sentinel"}),
        ("get_table_schema", {"table": "x" * 129}),
    ],
)
def test_tool_error_rejects_unsafe_operations_and_identifiers(
    operation: str,
    identifiers: dict[str, str],
) -> None:
    from mcp_stdio.core.errors import ErrorCategory, ToolError

    with pytest.raises(ValueError):
        ToolError.create(
            category=ErrorCategory.INVALID_INPUT,
            operation=operation,
            retryable=False,
            identifiers=identifiers,
        )


def test_unexpected_mapper_does_not_accept_a_caller_logger() -> None:
    from mcp_stdio.core.errors import unexpected_tool_error

    assert "logger" not in inspect.signature(unexpected_tool_error).parameters


def test_unexpected_exception_is_generic_and_logged_with_correlation_id(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_stdio.core.errors import unexpected_tool_error

    secret = "unexpected-exception-unknown-sentinel"
    error_logger = logging.getLogger("mcp_stdio.errors")
    previous_level = error_logger.level
    previous_propagate = error_logger.propagate
    error_logger.handlers.clear()
    error_logger.setLevel(logging.ERROR)
    error_logger.propagate = False
    monkeypatch.setattr(logging, "lastResort", logging.StreamHandler())
    try:
        try:
            raise RuntimeError(f"raw upstream failure without structural label {secret}")
        except RuntimeError as error:
            mapped = unexpected_tool_error(
                error,
                operation="create_notebook",
                identifiers={"notebook": "safe-notebook-id"},
            )
    finally:
        error_logger.setLevel(previous_level)
        error_logger.propagate = previous_propagate

    captured = capsys.readouterr()
    payload_text = json.dumps(mapped.to_dict())

    assert mapped.category.value == "UPSTREAM_ERROR"
    assert mapped.message == "The upstream operation failed."
    assert mapped.retryable is False
    assert mapped.identifiers == {"notebook": "safe-notebook-id"}
    assert mapped.correlation_id in captured.err
    assert "unexpected exception during create_notebook" in captured.err
    assert secret not in payload_text
    assert "raw upstream failure" not in payload_text
    assert secret not in captured.err
    assert "RuntimeError" not in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""
    logging.getLogger("mcp_stdio").handlers.clear()
