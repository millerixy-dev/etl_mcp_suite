"""Secret-safe stderr logging with no import-time configuration."""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable

_LOGGER_NAME = "mcp_stdio"
_REDACTED = "[REDACTED]"
_SENSITIVE_FIELD = re.compile(
    r"""
    (?<![A-Za-z0-9_])
    (?:\\?["'])?
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
    (?:\\?["'])?
    \s*[:=]\s*
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)
_STANDALONE_BEARER = re.compile(r"(?<![A-Za-z0-9_])bearer\s+", flags=re.IGNORECASE)
_CORRELATION_ID = re.compile(
    r"""
    (?<![A-Za-z0-9_])correlation_id\s*=\s*
    (?P<value>
        [0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-
        [0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}
    )
    (?![0-9A-Fa-f-])
    """,
    flags=re.VERBOSE,
)
_FORMAT_FAILURE = "ERROR mcp_stdio logging record formatting failed safely"


def _split_line_ending(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith(("\r", "\n")):
        return line[:-1], line[-1:]
    return line, ""


def _correlation_suffix(line: str) -> str:
    match = _CORRELATION_ID.search(line)
    if match is None:
        return ""
    return f" correlation_id={match.group('value')}"


def _redact_sensitive_line(line: str) -> tuple[str, bool]:
    field_match = _SENSITIVE_FIELD.search(line)
    bearer_match = _STANDALONE_BEARER.search(line)
    if field_match is None and bearer_match is None:
        return line, False

    if field_match is not None and (
        bearer_match is None or field_match.start() <= bearer_match.start()
    ):
        safe_prefix = line[: field_match.end()]
    else:
        assert bearer_match is not None
        safe_prefix = line[: bearer_match.start()]
    return f"{safe_prefix}{_REDACTED}{_correlation_suffix(line)}", True


def _redact_structure(value: str) -> str:
    redacted_lines: list[str] = []
    redact_continuation = False
    for raw_line in value.splitlines(keepends=True):
        line, line_ending = _split_line_ending(raw_line)
        if redact_continuation and line.startswith((" ", "\t")):
            indentation = line[: len(line) - len(line.lstrip(" \t"))]
            redacted_lines.append(
                f"{indentation}{_REDACTED}{_correlation_suffix(line)}{line_ending}"
            )
            continue

        redact_continuation = False
        redacted_line, contains_sensitive_data = _redact_sensitive_line(line)
        redacted_lines.append(f"{redacted_line}{line_ending}")
        redact_continuation = contains_sensitive_data
    return "".join(redacted_lines)


class _Redactor:
    """Redact configured values and common credential-bearing text forms."""

    def __init__(self, secret_values: Iterable[str]) -> None:
        self._secret_values = tuple(
            sorted({value for value in secret_values if value}, key=len, reverse=True)
        )

    def redact(self, value: str) -> str:
        redacted = _redact_structure(value)
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
