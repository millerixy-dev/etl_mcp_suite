"""Tests for stable, secret-safe tool error mapping."""

from __future__ import annotations

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
        message="The requested table was not found.",
        retryable=False,
        identifiers={"database": "analytics", "table": "daily_sales"},
    )

    payload = error.to_dict()

    assert payload == {
        "category": "NOT_FOUND",
        "operation": "get_table_schema",
        "message": "The requested table was not found.",
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
        message="The upstream request timed out.",
        retryable=True,
    )
    second = ToolError.create(
        category=ErrorCategory.TIMEOUT,
        operation="get_paragraph_status",
        message="The upstream request timed out.",
        retryable=True,
    )

    assert first.correlation_id != second.correlation_id


def test_unexpected_exception_is_generic_and_logged_with_correlation_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_stdio.core.errors import unexpected_tool_error
    from mcp_stdio.core.logging import configure_logging

    secret = "unexpected-exception-secret-sentinel"
    logger = configure_logging(debug=True, secret_values=(secret,))
    try:
        raise RuntimeError(
            f"raw upstream failure password={secret} Authorization: Bearer raw-header-token"
        )
    except RuntimeError as error:
        mapped = unexpected_tool_error(
            error,
            operation="create_notebook",
            logger=logger,
            identifiers={"notebook": "safe-notebook-id"},
        )

    captured = capsys.readouterr()
    payload_text = json.dumps(mapped.to_dict())

    assert mapped.category.value == "UPSTREAM_ERROR"
    assert mapped.message == "The operation failed unexpectedly."
    assert mapped.retryable is False
    assert mapped.identifiers == {"notebook": "safe-notebook-id"}
    assert mapped.correlation_id in captured.err
    assert "unexpected exception during create_notebook" in captured.err
    assert "RuntimeError" in captured.err
    assert secret not in payload_text
    assert "raw upstream failure" not in payload_text
    assert secret not in captured.err
    assert "raw-header-token" not in captured.err
    assert captured.out == ""
    logging.getLogger("mcp_stdio").handlers.clear()
