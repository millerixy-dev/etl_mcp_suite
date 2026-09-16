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
        env_prefix="ZEPPELIN",
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
    assert expected.sql_write_allowed_databases == ("tmp_dc_ep",)
    assert expected.sh_allowed_commands == ()
    assert expected.sql_forbidden_keywords == ("DROP", "TRUNCATE")
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
def test_configuration_rejects_partial_credentials_safely(tmp_path: Path, field: str) -> None:
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
        ("sql_write_allowed_databases", "tmp_dc_ep"),
        ("sql_write_allowed_databases", ["1bad"]),
        ("sql_write_allowed_databases", ["tmp_dc_ep", "tmp_dc_ep"]),
        ("sql_write_allowed_databases", ["bad db"]),
        ("sh_allowed_commands", "echo"),
        ("sh_allowed_commands", ["bad cmd"]),
        ("sh_allowed_commands", ["echo", "echo"]),
        ("sql_forbidden_keywords", "DROP"),
        ("sql_forbidden_keywords", ["1bad"]),
        ("sql_forbidden_keywords", ["DROP", "drop"]),
        ("sql_forbidden_keywords", ["bad kw"]),
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
def test_configuration_rejects_unknown_fields(tmp_path: Path, section: str, field: str) -> None:
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


def test_write_safety_settings_load_case_sensitive_unique_and_immutable(
    tmp_path: Path,
) -> None:
    document = _document()
    settings = document["settings"]
    assert isinstance(settings, dict)
    settings["sql_write_allowed_databases"] = ["tmp_dc_ep", "staging_db"]
    settings["sh_allowed_commands"] = ["echo", "cat"]

    loaded = _load(_write_json(tmp_path / "zeppelin.json", document))

    assert loaded.settings.sql_write_allowed_databases == ("tmp_dc_ep", "staging_db")
    assert loaded.settings.sh_allowed_commands == ("echo", "cat")
    assert isinstance(loaded.settings.sql_write_allowed_databases, tuple)
    assert isinstance(loaded.settings.sh_allowed_commands, tuple)


def test_write_safety_settings_support_environment_overrides(
    tmp_path: Path,
) -> None:
    loaded = _load(
        _write_json(tmp_path / "zeppelin.json", _document()),
        {
            "MCP_STDIO__SETTINGS__SQL_WRITE_ALLOWED_DATABASES": '["tmp_dc_ep","staging_db"]',
            "MCP_STDIO__SETTINGS__SH_ALLOWED_COMMANDS": '["echo"]',
        },
    )

    assert loaded.settings.sql_write_allowed_databases == ("tmp_dc_ep", "staging_db")
    assert loaded.settings.sh_allowed_commands == ("echo",)


def test_sql_forbidden_keywords_default_to_drop_and_truncate(
    tmp_path: Path,
) -> None:
    loaded = _load(_write_json(tmp_path / "zeppelin.json", _document()))
    assert loaded.settings.sql_forbidden_keywords == ("DROP", "TRUNCATE")
    assert isinstance(loaded.settings.sql_forbidden_keywords, tuple)


def test_sql_forbidden_keywords_normalize_to_uppercase(tmp_path: Path) -> None:
    document = _document()
    settings = document["settings"]
    assert isinstance(settings, dict)
    settings["sql_forbidden_keywords"] = ["drop", "Truncate", "CREATE"]
    loaded = _load(_write_json(tmp_path / "zeppelin.json", document))
    assert loaded.settings.sql_forbidden_keywords == ("DROP", "TRUNCATE", "CREATE")


def test_sql_forbidden_keywords_support_environment_override(
    tmp_path: Path,
) -> None:
    loaded = _load(
        _write_json(tmp_path / "zeppelin.json", _document()),
        {
            "MCP_STDIO__SETTINGS__SQL_FORBIDDEN_KEYWORDS": '["DROP","CREATE"]',
        },
    )
    assert loaded.settings.sql_forbidden_keywords == ("DROP", "CREATE")


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
        "sql_write_allowed_databases",
        "sh_allowed_commands",
        "sql_forbidden_keywords",
        "restartable_interpreter_settings",
    }
    assert set(ZeppelinSecrets.model_fields) == {"username", "password"}


def test_restartable_interpreter_settings_default_to_empty(tmp_path: Path) -> None:
    loaded = _load(_write_json(tmp_path / "zeppelin.json", _document()))
    assert loaded.settings.restartable_interpreter_settings == ()


def test_restartable_interpreter_settings_preserve_opaque_ids_exactly(
    tmp_path: Path,
) -> None:
    document = _document()
    settings = document["settings"]
    assert isinstance(settings, dict)
    settings["restartable_interpreter_settings"] = [
        "2AY6GV7Q3",
        "../spark?scope=note#v1",
        "Spark",
        "spark",
    ]

    loaded = _load(_write_json(tmp_path / "zeppelin.json", document))

    assert loaded.settings.restartable_interpreter_settings == (
        "2AY6GV7Q3",
        "../spark?scope=note#v1",
        "Spark",
        "spark",
    )
    assert isinstance(loaded.settings.restartable_interpreter_settings, tuple)


@pytest.mark.parametrize("value", ["", "id\nnext", "id\x00next", "x" * 513, 123, True])
def test_restartable_interpreter_settings_reject_unsafe_or_non_string_entries(
    tmp_path: Path, value: object
) -> None:
    document = _document()
    settings = document["settings"]
    assert isinstance(settings, dict)
    settings["restartable_interpreter_settings"] = [value]

    with pytest.raises(ConfigError) as exc_info:
        _load(_write_json(tmp_path / "zeppelin.json", document))

    assert str(exc_info.value).startswith("CONFIG_ERROR: invalid configuration at settings")
    if value:
        assert str(value) not in str(exc_info.value)


def test_restartable_interpreter_settings_reject_duplicate_entries(
    tmp_path: Path,
) -> None:
    document = _document()
    settings = document["settings"]
    assert isinstance(settings, dict)
    settings["restartable_interpreter_settings"] = ["spark", "spark"]
    with pytest.raises(ConfigError):
        _load(_write_json(tmp_path / "zeppelin.json", document))


def test_restartable_interpreter_settings_use_configured_opaque_id_bound(
    tmp_path: Path,
) -> None:
    setting_id = "opaque-id"
    rejected = _document()
    rejected_settings = rejected["settings"]
    assert isinstance(rejected_settings, dict)
    rejected_settings["max_opaque_id_chars"] = len(setting_id) - 1
    rejected_settings["restartable_interpreter_settings"] = [setting_id]

    with pytest.raises(ConfigError) as exc_info:
        _load(_write_json(tmp_path / "rejected.json", rejected))

    assert str(exc_info.value) == "CONFIG_ERROR: invalid configuration at settings"
    assert setting_id not in str(exc_info.value)

    accepted = _document()
    accepted_settings = accepted["settings"]
    assert isinstance(accepted_settings, dict)
    accepted_settings["max_opaque_id_chars"] = len(setting_id)
    accepted_settings["restartable_interpreter_settings"] = [setting_id]

    loaded = _load(_write_json(tmp_path / "accepted.json", accepted))

    assert loaded.settings.restartable_interpreter_settings == (setting_id,)


def test_plugin_restart_allowlist_override_has_precedence_and_uses_json_array(
    tmp_path: Path,
) -> None:
    document = _document()
    settings = document["settings"]
    assert isinstance(settings, dict)
    settings["restartable_interpreter_settings"] = ["file-setting"]

    loaded = _load(
        _write_json(tmp_path / "zeppelin.json", document),
        {
            "MCP_STDIO__SETTINGS__RESTARTABLE_INTERPRETER_SETTINGS": '["generic-setting"]',
            "ZEPPELIN_RESTARTABLE_INTERPRETER_SETTINGS": (
                '["spark_prod","2AY6GV7Q3","../spark?scope=note#v1"]'
            ),
        },
    )

    assert loaded.settings.restartable_interpreter_settings == (
        "spark_prod",
        "2AY6GV7Q3",
        "../spark?scope=note#v1",
    )


def test_plugin_restart_allowlist_override_rejects_scalar_value(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc_info:
        _load(
            _write_json(tmp_path / "zeppelin.json", _document()),
            {"ZEPPELIN_RESTARTABLE_INTERPRETER_SETTINGS": '"spark_prod"'},
        )

    assert "settings.restartable_interpreter_settings" in str(exc_info.value)
    assert "spark_prod" not in str(exc_info.value)
