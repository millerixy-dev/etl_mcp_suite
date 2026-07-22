"""Tests for stderr-only logging and final-output redaction."""

from __future__ import annotations

import logging

import pytest


def test_logging_writes_only_redacted_text_to_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_stdio.core.logging import configure_logging

    password = "normal-message-password-sentinel"
    token = "structured-token-sentinel"
    cookie = "structured-cookie-sentinel"
    authorization = "authorization-header-sentinel"
    logger = configure_logging(
        secret_values=(password, token, cookie, authorization),
    )

    logger.info("login password=%s", password)
    logger.warning(
        "request payload=%s",
        {
            "headers": {"Authorization": f"Bearer {authorization}"},
            "token": token,
            "cookie": cookie,
        },
    )
    captured = capsys.readouterr()

    assert "login" in captured.err
    assert "request payload" in captured.err
    assert "[REDACTED]" in captured.err
    assert password not in captured.err
    assert token not in captured.err
    assert cookie not in captured.err
    assert authorization not in captured.err
    assert "Bearer" not in captured.err
    assert captured.out == ""
    logging.getLogger("mcp_stdio").handlers.clear()


@pytest.mark.parametrize(
    ("message", "secret_values"),
    [
        (
            "password='multi word password unknown sentinel'",
            ("multi word password unknown sentinel",),
        ),
        (
            'Authorization: "Bearer quoted authorization unknown sentinel"',
            ("quoted authorization unknown sentinel",),
        ),
        (
            "Cookie: session=cookie-first-unknown; refresh=cookie-second-unknown",
            ("cookie-first-unknown", "cookie-second-unknown"),
        ),
        (
            "Proxy-Authorization: 'Basic proxy authorization unknown sentinel'",
            ("proxy authorization unknown sentinel",),
        ),
    ],
)
def test_structural_redaction_removes_complete_unknown_sensitive_values(
    message: str,
    secret_values: tuple[str, ...],
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_stdio.core.logging import configure_logging

    logger = configure_logging()

    logger.info(message)
    captured = capsys.readouterr()

    assert "[REDACTED]" in captured.err
    for secret in secret_values:
        assert secret not in captured.err
    assert captured.out == ""
    logging.getLogger("mcp_stdio").handlers.clear()


def test_structural_redaction_runs_before_configured_literal_replacement(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_stdio.core.logging import configure_logging

    leaked_value = "must-not-leak-after-key-replacement"
    logger = configure_logging(secret_values=("password",))

    logger.info("password=%s", leaked_value)
    captured = capsys.readouterr()

    assert leaked_value not in captured.err
    assert captured.out == ""
    logging.getLogger("mcp_stdio").handlers.clear()


@pytest.mark.parametrize(
    ("message", "sentinels"),
    [
        (
            'password="unterminated multi word secret',
            ("unterminated", "multi word secret"),
        ),
        (
            r'body={\"password\":\"escaped-json-secret\"}',
            ("escaped-json-secret",),
        ),
    ],
)
def test_sensitive_field_detection_discards_malformed_or_escaped_line_suffix(
    message: str,
    sentinels: tuple[str, ...],
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_stdio.core.logging import configure_logging

    logger = configure_logging()

    logger.info(message)
    captured = capsys.readouterr()

    assert "[REDACTED]" in captured.err
    for sentinel in sentinels:
        assert sentinel not in captured.err
    assert captured.out == ""
    logging.getLogger("mcp_stdio").handlers.clear()


@pytest.mark.parametrize(
    ("message", "sentinel"),
    [
        ("headers[Authorization]=Basic basic-secret-sentinel", "basic-secret-sentinel"),
        (
            "headers['Authorization']=Basic quoted-basic-secret-sentinel",
            "quoted-basic-secret-sentinel",
        ),
        ("credentials[password]=password-secret-sentinel", "password-secret-sentinel"),
        ("headers[Cookie]=session=cookie-secret-sentinel", "cookie-secret-sentinel"),
        ("`password`=backtick-secret-sentinel", "backtick-secret-sentinel"),
    ],
)
def test_structured_sensitive_key_wrappers_fail_closed(
    message: str,
    sentinel: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_stdio.core.logging import configure_logging

    logger = configure_logging()

    logger.info(message)
    captured = capsys.readouterr()

    assert "[REDACTED]" in captured.err
    assert sentinel not in captured.err
    assert sentinel not in captured.out
    assert captured.out == ""
    logging.getLogger("mcp_stdio").handlers.clear()


@pytest.mark.parametrize(
    ("message", "sentinels"),
    [
        (
            "Cookie: session=first-cookie-secret\n csrf=second-cookie-secret",
            ("first-cookie-secret", "second-cookie-secret"),
        ),
        (
            "Authorization: Bearer first-auth-secret\n continuation-auth-secret",
            ("first-auth-secret", "continuation-auth-secret"),
        ),
        (
            "request Bearer first-bearer-secret\n continuation-bearer-secret",
            ("first-bearer-secret", "continuation-bearer-secret"),
        ),
    ],
)
def test_sensitive_lines_redact_immediately_indented_continuations(
    message: str,
    sentinels: tuple[str, ...],
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_stdio.core.logging import configure_logging

    logger = configure_logging()

    logger.info(message)
    captured = capsys.readouterr()

    for sentinel in sentinels:
        assert sentinel not in captured.err
    assert captured.out == ""
    logging.getLogger("mcp_stdio").handlers.clear()


def test_existing_redaction_marker_does_not_gain_bracket_artifacts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_stdio.core.logging import configure_logging

    logger = configure_logging()

    logger.info("password=[REDACTED]")
    captured = capsys.readouterr()

    assert captured.err.count("[REDACTED]") == 1
    assert "]]" not in captured.err
    assert captured.out == ""
    logging.getLogger("mcp_stdio").handlers.clear()


@pytest.mark.parametrize(
    "message",
    [
        "Cookie: correlation_id={correlation_id}",
        "password=correlation_id={correlation_id}",
        "Authorization: Bearer correlation_id={correlation_id}",
    ],
)
def test_untrusted_sensitive_message_cannot_restore_correlation_id(
    message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_stdio.core.logging import configure_logging

    correlation_id = "123e4567-e89b-12d3-a456-426614174000"
    logger = configure_logging()

    logger.info(message.format(correlation_id=correlation_id))
    captured = capsys.readouterr()

    assert correlation_id not in captured.err
    assert captured.out == ""
    logging.getLogger("mcp_stdio").handlers.clear()


def test_malformed_format_arguments_fail_closed_without_logging_raw_arguments(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_stdio.core.logging import configure_logging

    secret = "malformed-format-argument-unknown-sentinel"
    logger = configure_logging()
    previous_raise_exceptions = logging.raiseExceptions
    logging.raiseExceptions = True
    try:
        logger.info("password=%s %s", secret)
    finally:
        logging.raiseExceptions = previous_raise_exceptions
    captured = capsys.readouterr()

    assert "logging record formatting failed safely" in captured.err
    assert secret not in captured.err
    assert "Arguments:" not in captured.err
    assert captured.out == ""
    logging.getLogger("mcp_stdio").handlers.clear()


def test_debug_traceback_is_redacted_after_rendering(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_stdio.core.logging import configure_logging

    known_secret = "debug-known-secret-sentinel"
    traceback_password = "debug-traceback-password-sentinel"
    traceback_token = "debug-traceback-token-sentinel"
    traceback_cookie = "debug-traceback-cookie-sentinel"
    logger = configure_logging(debug=True, secret_values=(known_secret,))

    try:
        raise RuntimeError(
            f"request failed {known_secret} password={traceback_password} "
            f"Authorization: Bearer {traceback_token} cookie={traceback_cookie}"
        )
    except RuntimeError:
        logger.exception(
            "upstream headers=%s",
            {"Authorization": f"Bearer {traceback_token}", "Cookie": traceback_cookie},
        )

    captured = capsys.readouterr()

    assert "Traceback" in captured.err
    assert "RuntimeError" in captured.err
    assert "[REDACTED]" in captured.err
    assert known_secret not in captured.err
    assert traceback_password not in captured.err
    assert traceback_token not in captured.err
    assert traceback_cookie not in captured.err
    assert "Bearer" not in captured.err
    assert captured.out == ""
    logging.getLogger("mcp_stdio").handlers.clear()


def test_reconfiguration_replaces_handlers_without_duplicating_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_stdio.core.logging import configure_logging

    configure_logging()
    logger = configure_logging()

    logger.info("one diagnostic line")
    captured = capsys.readouterr()

    assert captured.err.count("one diagnostic line") == 1
    assert captured.out == ""
    logging.getLogger("mcp_stdio").handlers.clear()
