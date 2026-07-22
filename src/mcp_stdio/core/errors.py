"""Stable, transport-independent application error boundary."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
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


def _empty_identifiers() -> dict[str, str]:
    return {}


@dataclass(frozen=True, slots=True)
class ToolError:
    """A safe error value ready for transport-specific serialization."""

    category: ErrorCategory
    operation: str
    message: str
    retryable: bool
    correlation_id: str
    identifiers: Mapping[str, str] = field(default_factory=_empty_identifiers)

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifiers", MappingProxyType(dict(self.identifiers)))

    @classmethod
    def create(
        cls,
        *,
        category: ErrorCategory,
        operation: str,
        message: str,
        retryable: bool,
        identifiers: Mapping[str, str] | None = None,
    ) -> ToolError:
        """Create one error with a fresh diagnostic correlation identifier."""

        return cls(
            category=category,
            operation=operation,
            message=message,
            retryable=retryable,
            identifiers={} if identifiers is None else identifiers,
            correlation_id=str(uuid4()),
        )

    def to_dict(self) -> dict[str, object]:
        """Return only the stable, explicitly safe public fields."""

        return {
            "category": self.category.value,
            "operation": self.operation,
            "message": self.message,
            "retryable": self.retryable,
            "identifiers": dict(self.identifiers),
            "correlation_id": self.correlation_id,
        }


def unexpected_tool_error(
    exception: Exception,
    *,
    operation: str,
    logger: logging.Logger,
    identifiers: Mapping[str, str] | None = None,
) -> ToolError:
    """Map and diagnose an uncategorized exception without exposing its text."""

    tool_error = ToolError.create(
        category=ErrorCategory.UPSTREAM_ERROR,
        operation=operation,
        message="The operation failed unexpectedly.",
        retryable=False,
        identifiers=identifiers,
    )
    logger.error(
        "unexpected exception during %s correlation_id=%s",
        operation,
        tool_error.correlation_id,
        exc_info=(type(exception), exception, exception.__traceback__),
    )
    return tool_error
