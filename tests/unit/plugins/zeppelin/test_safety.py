"""Unit tests for the decoupled paragraph content safety hook."""

from __future__ import annotations

import pytest

from mcp_stdio.plugins.zeppelin.safety import (
    InterpreterAllowlistChecker,
    ParagraphSafetyHook,
    ShCommandChecker,
    SqlForbiddenKeywordChecker,
    SqlWriteTargetChecker,
    build_default_safety_hook,
)


def test_interpreter_allowlist_checker_rejects_non_allowlisted() -> None:
    checker = InterpreterAllowlistChecker(frozenset({"spark.sql", "sh"}))
    with pytest.raises(ValueError):
        checker.check("spark", "SELECT 1")


def test_interpreter_allowlist_checker_allows_allowlisted() -> None:
    checker = InterpreterAllowlistChecker(frozenset({"spark.sql", "sh"}))
    checker.check("spark.sql", "SELECT 1")


def test_interpreter_allowlist_checker_message_names_interpreter() -> None:
    checker = InterpreterAllowlistChecker(frozenset({"spark.sql", "sh"}))
    with pytest.raises(ValueError, match="'spark'"):
        checker.check("spark", "SELECT 1")


def test_sql_forbidden_keyword_checker_rejects_drop_regardless_of_database() -> None:
    checker = SqlForbiddenKeywordChecker(frozenset({"DROP", "TRUNCATE"}))
    with pytest.raises(ValueError):
        checker.check("spark.sql", "DROP TABLE tmp_dc_ep.my_table")


def test_sql_forbidden_keyword_checker_allows_non_forbidden_write() -> None:
    checker = SqlForbiddenKeywordChecker(frozenset({"DROP", "TRUNCATE"}))
    checker.check("spark.sql", "INSERT INTO tmp_dc_ep.my_table VALUES (1)")


def test_sql_forbidden_keyword_checker_skips_non_sql_interpreter() -> None:
    checker = SqlForbiddenKeywordChecker(frozenset({"DROP", "TRUNCATE"}))
    checker.check("sh", "DROP something")


def test_sql_write_target_checker_rejects_non_approved_database() -> None:
    checker = SqlWriteTargetChecker(frozenset({"tmp_dc_ep"}))
    with pytest.raises(ValueError):
        checker.check("spark.sql", "INSERT INTO other_db.my_table VALUES (1)")


def test_sql_write_target_checker_allows_approved_database() -> None:
    checker = SqlWriteTargetChecker(frozenset({"tmp_dc_ep"}))
    checker.check("spark.sql", "CREATE TABLE tmp_dc_ep.my_table (id int)")


def test_sql_write_target_checker_skips_non_sql_interpreter() -> None:
    checker = SqlWriteTargetChecker(frozenset({"tmp_dc_ep"}))
    checker.check("sh", "INSERT anything")


def test_sh_command_checker_rejects_non_allowlisted() -> None:
    checker = ShCommandChecker(frozenset({"echo", "cat"}))
    with pytest.raises(ValueError):
        checker.check("sh", "rm -rf /tmp/x")


def test_sh_command_checker_allows_allowlisted() -> None:
    checker = ShCommandChecker(frozenset({"echo", "cat"}))
    checker.check("sh", "echo hello")


def test_sh_command_checker_skips_non_sh_interpreter() -> None:
    checker = ShCommandChecker(frozenset({"echo"}))
    checker.check("spark.sql", "SELECT 1")


def test_paragraph_safety_hook_runs_all_checkers_and_passes() -> None:
    hook = ParagraphSafetyHook(
        checkers=(
            InterpreterAllowlistChecker(frozenset({"spark.sql", "sh"})),
            SqlForbiddenKeywordChecker(frozenset({"DROP", "TRUNCATE"})),
            SqlWriteTargetChecker(frozenset({"tmp_dc_ep"})),
            ShCommandChecker(frozenset({"echo"})),
        )
    )
    hook.enforce("spark.sql", "INSERT INTO tmp_dc_ep.my_table VALUES (1)")
    hook.enforce("sh", "echo hello")


def test_paragraph_safety_hook_first_reject_wins() -> None:
    hook = ParagraphSafetyHook(
        checkers=(
            InterpreterAllowlistChecker(frozenset({"spark.sql"})),
            SqlForbiddenKeywordChecker(frozenset({"DROP"})),
        )
    )
    with pytest.raises(ValueError):
        hook.enforce("spark", "DROP TABLE tmp_dc_ep.x")


def test_paragraph_safety_hook_blacklist_before_whitelist_rejects_drop_on_approved_db() -> None:
    hook = ParagraphSafetyHook(
        checkers=(
            InterpreterAllowlistChecker(frozenset({"spark.sql"})),
            SqlForbiddenKeywordChecker(frozenset({"DROP", "TRUNCATE"})),
            SqlWriteTargetChecker(frozenset({"tmp_dc_ep"})),
        )
    )
    with pytest.raises(ValueError):
        hook.enforce("spark.sql", "DROP TABLE tmp_dc_ep.my_table")
    with pytest.raises(ValueError):
        hook.enforce("spark.sql", "TRUNCATE TABLE tmp_dc_ep.my_table")


def test_paragraph_safety_hook_allows_create_alter_on_approved_db() -> None:
    hook = ParagraphSafetyHook(
        checkers=(
            InterpreterAllowlistChecker(frozenset({"spark.sql"})),
            SqlForbiddenKeywordChecker(frozenset({"DROP", "TRUNCATE"})),
            SqlWriteTargetChecker(frozenset({"tmp_dc_ep"})),
        )
    )
    hook.enforce("spark.sql", "CREATE TABLE tmp_dc_ep.my_table (id int)")
    hook.enforce("spark.sql", "ALTER TABLE tmp_dc_ep.my_table ADD COLUMNS (x int)")


def test_paragraph_safety_hook_empty_checkers_passes_everything() -> None:
    hook = ParagraphSafetyHook(checkers=())
    hook.enforce("anything", "DROP TABLE x")


def test_build_default_safety_hook_assembles_canonical_order() -> None:
    hook = build_default_safety_hook(
        allowed_interpreters=("spark.sql", "sh"),
        sql_forbidden_keywords=("DROP", "TRUNCATE"),
        sql_write_allowed_databases=("tmp_dc_ep",),
        sh_allowed_commands=("echo",),
    )
    assert len(hook.checkers) == 4
    assert isinstance(hook.checkers[0], InterpreterAllowlistChecker)
    assert isinstance(hook.checkers[1], SqlForbiddenKeywordChecker)
    assert isinstance(hook.checkers[2], SqlWriteTargetChecker)
    assert isinstance(hook.checkers[3], ShCommandChecker)


def test_build_default_safety_hook_enforces_blacklist_before_whitelist() -> None:
    hook = build_default_safety_hook(
        allowed_interpreters=("spark.sql",),
        sql_forbidden_keywords=("DROP", "TRUNCATE"),
        sql_write_allowed_databases=("tmp_dc_ep",),
        sh_allowed_commands=(),
    )
    with pytest.raises(ValueError):
        hook.enforce("spark.sql", "DROP TABLE tmp_dc_ep.my_table")
    hook.enforce("spark.sql", "CREATE TABLE tmp_dc_ep.my_table (id int)")
