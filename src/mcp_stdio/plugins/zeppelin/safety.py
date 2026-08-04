"""Decoupled, multi-level paragraph content safety hook.

The hook is the sole path from ``add_paragraph`` to the gateway. Each checker
is a single-responsibility policy built from configuration; the composite runs
them in order and the first rejection terminates the chain. Checkers depend
only on the pure validation functions in :mod:`models` - no HTTP, MCP, or
config-model imports - so they stay inside the application layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mcp_stdio.plugins.zeppelin.models import (
    validate_sh_command,
    validate_sql_forbidden_keywords,
    validate_sql_write_target,
)


class ParagraphChecker(Protocol):
    """A single paragraph content safety check."""

    def check(self, interpreter: str, body: str) -> None:
        """Raise ``ValueError`` when the paragraph content is rejected."""
        ...


@dataclass(frozen=True)
class InterpreterAllowlistChecker:
    """Reject paragraphs whose interpreter is not explicitly allowlisted."""

    allowed: frozenset[str]

    def check(self, interpreter: str, body: str) -> None:
        if interpreter not in self.allowed:
            raise ValueError(f"interpreter '{interpreter}' is not allowlisted")


@dataclass(frozen=True)
class SqlForbiddenKeywordChecker:
    """Reject SQL statements whose leading keyword is forbidden (any database)."""

    forbidden: frozenset[str]

    def check(self, interpreter: str, body: str) -> None:
        if "sql" in interpreter.lower():
            validate_sql_forbidden_keywords(body, self.forbidden)


@dataclass(frozen=True)
class SqlWriteTargetChecker:
    """Reject SQL writes targeting a non-allowlisted database."""

    allowed_databases: frozenset[str]

    def check(self, interpreter: str, body: str) -> None:
        if "sql" in interpreter.lower():
            validate_sql_write_target(body, tuple(self.allowed_databases))


@dataclass(frozen=True)
class ShCommandChecker:
    """Reject ``sh`` paragraphs whose first command is not allowlisted."""

    allowed_commands: frozenset[str]

    def check(self, interpreter: str, body: str) -> None:
        if interpreter == "sh":
            validate_sh_command(body, tuple(self.allowed_commands))


@dataclass(frozen=True)
class ParagraphSafetyHook:
    """Mandatory, ordered content safety gate.

    ``enforce`` runs every checker in order; the first rejection wins. This is
    the only path from ``add_paragraph`` to the gateway and cannot be bypassed.
    """

    checkers: tuple[ParagraphChecker, ...]

    def enforce(self, interpreter: str, body: str) -> None:
        for checker in self.checkers:
            checker.check(interpreter, body)


def build_default_safety_hook(
    *,
    allowed_interpreters: tuple[str, ...],
    sql_forbidden_keywords: tuple[str, ...],
    sql_write_allowed_databases: tuple[str, ...],
    sh_allowed_commands: tuple[str, ...],
) -> ParagraphSafetyHook:
    """Assemble the canonical four-checker hook from configuration values.

    Order is normative: the forbidden-keyword blacklist runs before the
    database allowlist so ``DROP TABLE tmp_dc_ep.x`` is rejected by the
    blacklist rather than passed by the whitelist.
    """

    return ParagraphSafetyHook(
        checkers=(
            InterpreterAllowlistChecker(frozenset(allowed_interpreters)),
            SqlForbiddenKeywordChecker(frozenset(sql_forbidden_keywords)),
            SqlWriteTargetChecker(frozenset(sql_write_allowed_databases)),
            ShCommandChecker(frozenset(sh_allowed_commands)),
        )
    )
