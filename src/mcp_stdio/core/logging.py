"""Secret-safe stderr logging with no import-time configuration."""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable

_LOGGER_NAME = "mcp_stdio"
_REDACTED = "[REDACTED]"
_SENSITIVE_KEY = r"""
    (?:
        authorization
        | proxy-authorization
        | password
        | passwd
        | token
        | access[_-]?token
        | refresh[_-]?token
        | api[_-]?key
        | cookie
        | set-cookie
    )
"""
_AUTH_OR_COOKIE_KEY = r"(?:authorization|proxy-authorization|cookie|set-cookie)"
_ORDINARY_SENSITIVE_KEY = r"""
    (?:
        password
        | passwd
        | token
        | access[_-]?token
        | refresh[_-]?token
        | api[_-]?key
    )
"""
_QUOTED_SENSITIVE_VALUE = re.compile(
    rf"""
    (?P<prefix>["']?{_SENSITIVE_KEY}["']?\s*[:=]\s*)
    (?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)
_AUTH_OR_COOKIE_VALUE = re.compile(
    rf"""
    (?P<prefix>["']?{_AUTH_OR_COOKIE_KEY}["']?\s*[:=]\s*)
    [^\r\n]*
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)
_UNQUOTED_SENSITIVE_VALUE = re.compile(
    r"""
    (?P<prefix>["']?"""
    + _ORDINARY_SENSITIVE_KEY
    + r"""["']?\s*[:=]\s*)
    [^\s,;}\]]+
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)
_BEARER_CREDENTIAL = re.compile(
    r"""
    \bbearer\s+
    (?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\r\n,;}\]]+)
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)
_FORMAT_FAILURE = "ERROR mcp_stdio logging record formatting failed safely"


class _Redactor:
    """Redact configured values and common credential-bearing text forms."""

    def __init__(self, secret_values: Iterable[str]) -> None:
        self._secret_values = tuple(
            sorted({value for value in secret_values if value}, key=len, reverse=True)
        )

    def redact(self, value: str) -> str:
        redacted = _QUOTED_SENSITIVE_VALUE.sub(
            lambda match: f"{match.group('prefix')}{_REDACTED}", value
        )
        redacted = _AUTH_OR_COOKIE_VALUE.sub(
            lambda match: f"{match.group('prefix')}{_REDACTED}", redacted
        )
        redacted = _UNQUOTED_SENSITIVE_VALUE.sub(
            lambda match: f"{match.group('prefix')}{_REDACTED}", redacted
        )
        redacted = _BEARER_CREDENTIAL.sub(_REDACTED, redacted)
        for secret in self._secret_values:
            redacted = redacted.replace(secret, _REDACTED)
        return redacted


class _RedactingFormatter(logging.Formatter):
    """Redact the final rendered record, including formatted tracebacks."""

    def __init__(self, redactor: _Redactor) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s")
        self._redactor = redactor

    def format(self, record: logging.LogRecord) -> str:
        try:
            return self._redactor.redact(super().format(record))
        except Exception:
            return _FORMAT_FAILURE


def configure_logging(
    *,
    debug: bool = False,
    secret_values: Iterable[str] = (),
) -> logging.Logger:
    """Configure the application logger with one redacting stderr handler."""

    logger = logging.getLogger(_LOGGER_NAME)
    for handler in logger.handlers:
        handler.close()
    logger.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_RedactingFormatter(_Redactor(secret_values)))
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False
    logger.disabled = False
    return logger
