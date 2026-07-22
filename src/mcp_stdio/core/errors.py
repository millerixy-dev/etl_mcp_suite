"""Stable, transport-independent application error boundary."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
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
_OPERATION_PATTERN = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*\Z")
_IDENTIFIER_KEY_PATTERN = _OPERATION_PATTERN
_IDENTIFIER_VALUE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}\Z")
_MAX_OPERATION_LENGTH = 64
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


@dataclass(frozen=True, slots=True)
class ToolError:
    """A safe error value ready for transport-specific serialization."""

    category: ErrorCategory
    operation: str
    retryable: bool
    identifiers: Mapping[str, str] = field(default_factory=_empty_identifiers)
    message: str = field(init=False)
    correlation_id: str = field(default_factory=_new_correlation_id, init=False)

    def __post_init__(self) -> None:
        category = cast(object, self.category)
        operation = cast(object, self.operation)
        retryable = cast(object, self.retryable)
        raw_identifiers = cast(Mapping[object, object], self.identifiers)

        if not isinstance(category, ErrorCategory):
            raise ValueError("category must be an ErrorCategory")
        if not isinstance(operation, str) or not (
            len(operation) <= _MAX_OPERATION_LENGTH
            and _OPERATION_PATTERN.fullmatch(operation)
        ):
            raise ValueError("operation must be a canonical tool operation")
        if type(retryable) is not bool:
            raise ValueError("retryable must be a boolean")

        try:
            identifier_items = dict(raw_identifiers)
        except (TypeError, ValueError):
            raise ValueError("identifiers must be a string mapping") from None
        identifiers: dict[str, str] = {}
        for key, value in identifier_items.items():
            normalized_key = key.lower() if isinstance(key, str) else ""
            if not (
                isinstance(key, str)
                and len(key) <= _MAX_OPERATION_LENGTH
                and _IDENTIFIER_KEY_PATTERN.fullmatch(key)
                and not any(part in normalized_key for part in _SENSITIVE_IDENTIFIER_KEY_PARTS)
            ):
                raise ValueError("identifier key is unsafe")
            if not isinstance(value, str) or not _IDENTIFIER_VALUE_PATTERN.fullmatch(value):
                raise ValueError("identifier value is unsafe")
            identifiers[key] = value

        object.__setattr__(self, "identifiers", MappingProxyType(identifiers))
        object.__setattr__(self, "message", _ERROR_MESSAGES[category])

    @classmethod
    def create(
        cls,
        *,
        category: ErrorCategory,
        operation: str,
        retryable: bool,
        identifiers: Mapping[str, str] | None = None,
    ) -> ToolError:
        """Create one error with a fresh diagnostic correlation identifier."""

        return cls(
            category=category,
            operation=operation,
            retryable=retryable,
            identifiers={} if identifiers is None else identifiers,
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
    identifiers: Mapping[str, str] | None = None,
) -> ToolError:
    """Map and diagnose an uncategorized exception without exposing its text."""

    tool_error = ToolError.create(
        category=ErrorCategory.UPSTREAM_ERROR,
        operation=operation,
        retryable=False,
        identifiers=identifiers,
    )
    logger = logging.getLogger("mcp_stdio.errors")
    logger.error(
        "unexpected exception during %s correlation_id=%s",
        operation,
        tool_error.correlation_id,
    )
    return tool_error
