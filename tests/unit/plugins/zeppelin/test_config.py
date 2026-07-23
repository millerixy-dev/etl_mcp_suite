"""Zeppelin configuration contract tests."""

from __future__ import annotations

import json
import traceback
from pathlib import Path

import pytest

from mcp_stdio.core.config import ConfigError, LoadedConfig, load_config
from mcp_stdio.plugins.zeppelin.config import ZeppelinSecrets, ZeppelinSettings


def _document() -> dict[str, object]:
    return {
        "version": 1,
        "plugin": "zeppelin",
        "settings": {"base_url": "https://zeppelin.example/gateway/zeppelin/"},
        "secrets": {},
    }


def _write_json(path: Path, document: object) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _write_yaml(path: Path) -> Path:
    path.write_text(
        """
version: 1
plugin: zeppelin
settings:
  base_url: https://zeppelin.example/gateway/zeppelin/
secrets: {}
""".lstrip(),
        encoding="utf-8",
    )
    return path


def _load(
    path: Path, environ: dict[str, str] | None = None
) -> LoadedConfig[ZeppelinSettings, ZeppelinSecrets]:
    return load_config(
        path,
        expected_plugin="zeppelin",
        settings_type=ZeppelinSettings,
        secrets_type=ZeppelinSecrets,
        environ={} if environ is None else environ,
    )


def test_yaml_and_json_load_equivalent_defaults_without_authentication(
    tmp_path: Path,
) -> None:
    yaml_config = _load(_write_yaml(tmp_path / "zeppelin.yaml"))
    json_config = _load(_write_json(tmp_path / "zeppelin.json", _document()))

    expected = ZeppelinSettings(base_url="https://zeppelin.example/gateway/zeppelin")
    assert yaml_config.settings == json_config.settings == expected
    assert expected.request_timeout_seconds == 30.0
    assert expected.max_response_bytes == 1_048_576
    assert expected.max_result_bytes == 65_536
    assert expected.max_notebook_name_chars == 256
    assert expected.max_paragraph_title_chars == 256
    assert expected.max_paragraph_body_bytes == 65_536
    assert expected.max_opaque_id_chars == 512
    assert expected.allowed_interpreters == ()
    assert isinstance(expected.allowed_interpreters, tuple)
    assert yaml_config.secrets.username is None
    assert yaml_config.secrets.password is None


def test_configuration_resolves_optional_paired_session_credentials(tmp_path: Path) -> None:
    document = _document()
    document["secrets"] = {
        "username": "ZEPPELIN_USERNAME",
        "password": "ZEPPELIN_PASSWORD",
    }

    loaded = _load(
        _write_json(tmp_path / "zeppelin.json", document),
        {
            "ZEPPELIN_USERNAME": "username-sentinel",
            "ZEPPELIN_PASSWORD": "password-sentinel",
        },
    )

    assert loaded.secrets.username is not None
    assert loaded.secrets.password is not None
    assert loaded.secrets.username.get_secret_value() == "username-sentinel"
    assert loaded.secrets.password.get_secret_value() == "password-sentinel"
    assert "username-sentinel" not in repr(loaded)
    assert "password-sentinel" not in repr(loaded.secrets)


@pytest.mark.parametrize("field", ["username", "password"])
def test_configuration_rejects_partial_credentials_safely(
    tmp_path: Path, field: str
) -> None:
    secret_value = "credential-sentinel"
    document = _document()
    document["secrets"] = {field: f"ZEPPELIN_{field.upper()}"}

    with pytest.raises(ConfigError) as exc_info:
        _load(
            _write_json(tmp_path / "zeppelin.json", document),
            {f"ZEPPELIN_{field.upper()}": secret_value},
        )

    rendered = "".join(
        traceback.format_exception(
            type(exc_info.value), exc_info.value, exc_info.value.__traceback__
        )
    )
    assert secret_value not in rendered
    assert "invalid configuration at secrets" in str(exc_info.value)


def test_allowed_interpreters_are_case_sensitive_unique_and_immutable(
    tmp_path: Path,
) -> None:
    document = _document()
    settings = document["settings"]
    assert isinstance(settings, dict)
    settings["allowed_interpreters"] = ["spark.sql", "Spark", "sh"]

    loaded = _load(_write_json(tmp_path / "zeppelin.json", document))

    assert loaded.settings.allowed_interpreters == ("spark.sql", "Spark", "sh")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("base_url", "ftp://zeppelin.example"),
        ("base_url", "https://user:pass@zeppelin.example"),
        ("base_url", "https://zeppelin.example/path?mode=unsafe"),
        ("base_url", "https://zeppelin.example/path#fragment"),
        ("base_url", "/relative/path"),
        ("base_url", 123),
        ("request_timeout_seconds", 0),
        ("request_timeout_seconds", 300.1),
        ("request_timeout_seconds", "30"),
        ("request_timeout_seconds", True),
        ("max_response_bytes", 0),
        ("max_response_bytes", 8_388_609),
        ("max_response_bytes", 1.5),
        ("max_result_bytes", 0),
        ("max_result_bytes", 1_048_577),
        ("max_notebook_name_chars", 0),
        ("max_notebook_name_chars", 1_025),
        ("max_paragraph_title_chars", 0),
        ("max_paragraph_title_chars", 1_025),
        ("max_paragraph_body_bytes", 0),
        ("max_paragraph_body_bytes", 1_048_577),
        ("max_opaque_id_chars", 0),
        ("max_opaque_id_chars", 4_097),
        ("allowed_interpreters", "spark.sql"),
        ("allowed_interpreters", ["spark sql"]),
        ("allowed_interpreters", ["1spark"]),
        ("allowed_interpreters", ["s" * 65]),
        ("allowed_interpreters", ["spark", "spark"]),
    ],
)
def test_settings_reject_invalid_or_non_strict_values(
    tmp_path: Path, field: str, value: object
) -> None:
    document = _document()
    settings = document["settings"]
    assert isinstance(settings, dict)
    settings[field] = value

    with pytest.raises(ConfigError) as exc_info:
        _load(_write_json(tmp_path / "zeppelin.json", document))

    assert f"settings.{field}" in str(exc_info.value)
    assert str(value) not in str(exc_info.value)


@pytest.mark.parametrize(
    ("section", "field"),
    [("settings", "token"), ("secrets", "cookie")],
)
def test_configuration_rejects_unknown_fields(
    tmp_path: Path, section: str, field: str
) -> None:
    document = _document()
    values = document[section]
    assert isinstance(values, dict)
    values[field] = "not-approved"

    with pytest.raises(ConfigError, match="unknown field"):
        _load(_write_json(tmp_path / "zeppelin.json", document))


def test_non_sensitive_environment_overrides_use_the_same_validation(
    tmp_path: Path,
) -> None:
    loaded = _load(
        _write_json(tmp_path / "zeppelin.json", _document()),
        {
            "MCP_STDIO__SETTINGS__MAX_RESULT_BYTES": "4096",
            "MCP_STDIO__SETTINGS__ALLOWED_INTERPRETERS": '["spark.sql"]',
        },
    )

    assert loaded.settings.max_result_bytes == 4_096
    assert loaded.settings.allowed_interpreters == ("spark.sql",)


def test_schema_contains_only_the_approved_v1_fields() -> None:
    assert set(ZeppelinSettings.model_fields) == {
        "base_url",
        "request_timeout_seconds",
        "max_response_bytes",
        "max_result_bytes",
        "max_notebook_name_chars",
        "max_paragraph_title_chars",
        "max_paragraph_body_bytes",
        "max_opaque_id_chars",
        "allowed_interpreters",
    }
    assert set(ZeppelinSecrets.model_fields) == {"username", "password"}
