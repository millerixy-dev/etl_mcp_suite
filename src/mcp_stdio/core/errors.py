"""Stable, transport-independent application error boundary."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import cast
from uuid import uuid4


class ErrorCategory(str, Enum):
    """Stable categories exposed at the MCP tool boundary."""

    CONFIG_ERROR = "CONFIG_ERROR"
    INVALID_INPUT = "INVALID_INPUT"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    NOT_FOUND = "NOT_FOUND"
    CONNECTION_FAILED = "CONNECTION_FAILED"
    TIMEOUT = "TIMEOUT"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    UNEXPECTED_RESPONSE = "UNEXPECTED_RESPONSE"


class ToolOperation(str, Enum):
    """Closed set of public V1 tools plus an internal fallback operation."""

    LIST_DATABASES = "list_databases"
    LIST_TABLES = "list_tables"
    GET_TABLE_SCHEMA = "get_table_schema"
    LIST_NOTEBOOKS = "list_notebooks"
    CREATE_NOTEBOOK = "create_notebook"
    ADD_PARAGRAPH = "add_paragraph"
    RUN_PARAGRAPH = "run_paragraph"
    GET_PARAGRAPH_STATUS = "get_paragraph_status"
    GET_PARAGRAPH_RESULT = "get_paragraph_result"
    GET_INTERPRETER_BINDINGS = "get_interpreter_bindings"
    RESTART_INTERPRETER = "restart_interpreter"
    CANCEL_PARAGRAPH = "cancel_paragraph"
    GET_SERVER_STATUS = "get_server_status"
    LIST_OBJECTS = "list_objects"
    GET_OBJECT = "get_object"
    SEARCH_OBJECTS = "search_objects"
    START_WORKFLOW = "start_workflow"
    GET_TASK_LOG = "get_task_log"
    EXTRACT_LOG_LINKS = "extract_log_links"
    FETCH_SPARK_EVENT_LOG = "fetch_spark_event_log"
    INSPECT_SPARK_EVENT_LOG = "inspect_spark_event_log"
    QUERY_SPARK_EVENTS = "query_spark_events"
    RUNTIME = "runtime"


_ERROR_MESSAGES: Mapping[ErrorCategory, str] = MappingProxyType(
    {
        ErrorCategory.CONFIG_ERROR: "Configuration is invalid.",
        ErrorCategory.INVALID_INPUT: "The request input is invalid.",
        ErrorCategory.AUTHENTICATION_FAILED: "Authentication failed.",
        ErrorCategory.PERMISSION_DENIED: "Permission was denied.",
        ErrorCategory.NOT_FOUND: "The requested resource was not found.",
        ErrorCategory.CONNECTION_FAILED: "Could not connect to the upstream service.",
        ErrorCategory.TIMEOUT: "The upstream operation timed out.",
        ErrorCategory.UPSTREAM_ERROR: "The upstream operation failed.",
        ErrorCategory.UNEXPECTED_RESPONSE: "The upstream response was not understood.",
    }
)
_ALLOWED_IDENTIFIER_KEYS: Mapping[ToolOperation, frozenset[str]] = MappingProxyType(
    {
        ToolOperation.LIST_DATABASES: frozenset(),
        ToolOperation.LIST_TABLES: frozenset({"database"}),
        ToolOperation.GET_TABLE_SCHEMA: frozenset({"database", "table"}),
        ToolOperation.LIST_NOTEBOOKS: frozenset(),
        ToolOperation.CREATE_NOTEBOOK: frozenset(),
        ToolOperation.ADD_PARAGRAPH: frozenset({"notebook_id"}),
        ToolOperation.RUN_PARAGRAPH: frozenset({"notebook_id", "paragraph_id"}),
        ToolOperation.GET_PARAGRAPH_STATUS: frozenset({"notebook_id", "paragraph_id"}),
        ToolOperation.GET_PARAGRAPH_RESULT: frozenset({"notebook_id", "paragraph_id"}),
        ToolOperation.GET_INTERPRETER_BINDINGS: frozenset({"notebook_id"}),
        ToolOperation.RESTART_INTERPRETER: frozenset({"setting_id", "notebook_id"}),
        ToolOperation.CANCEL_PARAGRAPH: frozenset({"notebook_id", "paragraph_id"}),
        ToolOperation.GET_SERVER_STATUS: frozenset(),
        ToolOperation.LIST_OBJECTS: frozenset(),
        ToolOperation.GET_OBJECT: frozenset(),
        ToolOperation.SEARCH_OBJECTS: frozenset(),
        ToolOperation.START_WORKFLOW: frozenset(),
        ToolOperation.GET_TASK_LOG: frozenset(),
        ToolOperation.EXTRACT_LOG_LINKS: frozenset(),
        ToolOperation.FETCH_SPARK_EVENT_LOG: frozenset({"application_id", "attempt_id"}),
        ToolOperation.INSPECT_SPARK_EVENT_LOG: frozenset({"application_id", "attempt_id"}),
        ToolOperation.QUERY_SPARK_EVENTS: frozenset({"application_id", "attempt_id"}),
        ToolOperation.RUNTIME: frozenset(),
    }
)
_MAX_IDENTIFIER_LENGTH = 256
_SENSITIVE_IDENTIFIER_KEY_PARTS = (
    "authorization",
    "cookie",
    "credential",
    "header",
    "password",
    "secret",
    "token",
)


def _empty_identifiers() -> dict[str, str]:
    return {}


def _new_correlation_id() -> str:
    return str(uuid4())


def _identifier_key_is_safe(key: object, *, operation: ToolOperation) -> bool:
    if not isinstance(key, str):
        return False
    normalized_key = key.lower()
    return (
        not any(part in normalized_key for part in _SENSITIVE_IDENTIFIER_KEY_PARTS)
        and key in _ALLOWED_IDENTIFIER_KEYS[operation]
    )


def _identifier_value_is_safe(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= _MAX_IDENTIFIER_LENGTH
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )


def safe_error_identifiers(
    operation: ToolOperation,
    identifiers: Mapping[str, object] | None,
) -> dict[str, str]:
    """Filter caller-supplied identifiers without truncating unsafe values."""

    raw_operation = cast(object, operation)
    if not isinstance(raw_operation, ToolOperation) or identifiers is None:
        return {}
    try:
        identifier_items = dict(identifiers)
    except Exception:
        return {}
    safe_identifiers: dict[str, str] = {}
    for key, value in identifier_items.items():
        if _identifier_key_is_safe(key, operation=operation) and _identifier_value_is_safe(value):
            assert isinstance(key, str)
            assert isinstance(value, str)
            safe_identifiers[key] = value
    return safe_identifiers


@dataclass(frozen=True, slots=True)
class ToolError:
    """A safe error value ready for transport-specific serialization."""

    category: ErrorCategory
    operation: ToolOperation
    retryable: bool
    identifiers: Mapping[str, str] = field(default_factory=_empty_identifiers)
    explanation: str | None = None
    message: str = field(init=False)
    correlation_id: str = field(default_factory=_new_correlation_id, init=False)

    def __post_init__(self) -> None:
        category = cast(object, self.category)
        operation = cast(object, self.operation)
        retryable = cast(object, self.retryable)
        raw_identifiers = cast(Mapping[object, object], self.identifiers)

        if not isinstance(category, ErrorCategory):
            raise ValueError("category must be an ErrorCategory")
        if not isinstance(operation, ToolOperation):
            raise ValueError("operation must be a supported ToolOperation")
        if type(retryable) is not bool:
            raise ValueError("retryable must be a boolean")
        explanation = cast(object, self.explanation)
        if explanation is not None and not isinstance(explanation, str):
            raise ValueError("explanation must be a string or None")

        try:
            identifier_items = dict(raw_identifiers)
        except Exception:
            raise ValueError("identifiers must be a string mapping") from None
        identifiers: dict[str, str] = {}
        for key, value in identifier_items.items():
            if not _identifier_key_is_safe(key, operation=operation):
                raise ValueError("identifier key is not allowed for the operation")
            if not _identifier_value_is_safe(value):
                raise ValueError("identifier value is unsafe")
            assert isinstance(key, str)
            assert isinstance(value, str)
            identifiers[key] = value

        object.__setattr__(self, "identifiers", MappingProxyType(identifiers))
        object.__setattr__(self, "message", _ERROR_MESSAGES[category])

    @classmethod
    def create(
        cls,
        *,
        category: ErrorCategory,
        operation: ToolOperation,
        retryable: bool,
        identifiers: Mapping[str, str] | None = None,
        explanation: str | None = None,
    ) -> ToolError:
        """Create one error with a fresh diagnostic correlation identifier."""

        return cls(
            category=category,
            operation=operation,
            retryable=retryable,
            identifiers={} if identifiers is None else identifiers,
            explanation=explanation,
        )

    def to_dict(self, *, secret_values: Iterable[str]) -> dict[str, object]:
        """Return only the stable, explicitly safe public fields."""

        secrets = tuple(secret for secret in secret_values if secret)
        safe_identifiers = {
            key: value
            for key, value in self.identifiers.items()
            if not any(secret in value for secret in secrets)
        }
        result: dict[str, object] = {
            "category": self.category.value,
            "operation": self.operation.value,
            "message": self.message,
            "retryable": self.retryable,
            "identifiers": safe_identifiers,
            "correlation_id": self.correlation_id,
        }
        if self.explanation and not any(secret in self.explanation for secret in secrets):
            result["explanation"] = self.explanation
        return result


def unexpected_tool_error(
    exception: Exception,
    *,
    operation: ToolOperation,
    identifiers: Mapping[str, str] | None = None,
) -> ToolError:
    """Map and diagnose an uncategorized exception without exposing its text."""

    try:
        tool_error = ToolError.create(
            category=ErrorCategory.UPSTREAM_ERROR,
            operation=operation,
            retryable=False,
            identifiers=identifiers,
        )
    except Exception:
        tool_error = ToolError.create(
            category=ErrorCategory.UPSTREAM_ERROR,
            operation=ToolOperation.RUNTIME,
            retryable=False,
        )
    logger = logging.getLogger("mcp_stdio.errors")
    try:
        logger.error(
            "unexpected exception during %s",
            tool_error.operation.value,
            extra={"_mcp_correlation_id": tool_error.correlation_id},
        )
    except Exception:
        pass
    return tool_error
