"""Secret-safe stderr logging with no import-time configuration."""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable

_LOGGER_NAME = "mcp_stdio"
_REDACTED = "[REDACTED]"
_SENSITIVE_KEY_VALUE = re.compile(
    r"""
    (?P<prefix>
        ["']?
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
        ["']?\s*[:=]\s*
    )
    (?P<quote>["']?)
    (?:(?:bearer|basic)\s+)?
    [^\s,'";}\]]+
    (?P=quote)
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)
_BEARER_CREDENTIAL = re.compile(
    r"\bbearer\s+[^\s,;'\"}\]]+",
    flags=re.IGNORECASE,
)


class _Redactor:
    """Redact configured values and common credential-bearing text forms."""

    def __init__(self, secret_values: Iterable[str]) -> None:
        self._secret_values = tuple(
            sorted({value for value in secret_values if value}, key=len, reverse=True)
        )

    def redact(self, value: str) -> str:
        redacted = value
        for secret in self._secret_values:
            redacted = redacted.replace(secret, _REDACTED)
        redacted = _SENSITIVE_KEY_VALUE.sub(
            lambda match: f"{match.group('prefix')}{_REDACTED}", redacted
        )
        return _BEARER_CREDENTIAL.sub(_REDACTED, redacted)


class _RedactingFormatter(logging.Formatter):
    """Redact the final rendered record, including formatted tracebacks."""

    def __init__(self, redactor: _Redactor) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s")
        self._redactor = redactor

    def format(self, record: logging.LogRecord) -> str:
        return self._redactor.redact(super().format(record))


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
