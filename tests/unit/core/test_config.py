"""Tests for versioned, secret-safe local configuration loading."""

from __future__ import annotations

import json
import socket
import traceback
import typing
from pathlib import Path
from typing import Annotated

import pytest
from pydantic import BaseModel, Field, SecretBytes, SecretStr, field_validator

from mcp_stdio.core.config import (
    ConfigError,
    LoadedConfig,
    SecretConfigModel,
    StrictConfigModel,
    load_config,
)


class ExampleSettings(StrictConfigModel):
    host: str
    port: int = 10_000
    tls: bool = False


class ExampleSecrets(SecretConfigModel):
    username: SecretStr
    password: SecretStr


class LengthCheckedSecrets(SecretConfigModel):
    username: SecretStr
    password: Annotated[SecretStr, Field(min_length=64)]


class NestedConnectionSettings(StrictConfigModel):
    endpoint: str


class SettingsWithNestedModel(StrictConfigModel):
    connection: NestedConnectionSettings


class UnsafeSecrets(BaseModel):
    password: str


class ByteSecrets(SecretConfigModel):
    certificate: SecretBytes


class OptionalAuthSecrets(SecretConfigModel):
    token: SecretStr | None = None


class SettingsWithModelOrMapping(StrictConfigModel):
    connection: NestedConnectionSettings | dict[str, object]


class LegacyOptionalAuthSecrets(SecretConfigModel):
    token: typing.Optional[SecretStr] = None  # noqa: UP045


class ExplodingValidatorSecrets(SecretConfigModel):
    password: SecretStr

    @field_validator("password")
    @classmethod
    def reject_password(cls, value: SecretStr) -> SecretStr:
        raise TypeError(f"validator leaked:{value.get_secret_value()}")


def _write_yaml(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def _write_json(path: Path, document: object) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _valid_document() -> dict[str, object]:
    return {
        "version": 1,
        "plugin": "hive",
        "settings": {"host": "hive.example.internal", "port": 10_000, "tls": False},
        "secrets": {"username": "HIVE_USERNAME", "password": "HIVE_PASSWORD"},
    }


def _load(
    path: Path, environ: dict[str, str] | None = None
) -> LoadedConfig[ExampleSettings, ExampleSecrets]:
    return load_config(
        path,
        expected_plugin="hive",
        settings_type=ExampleSettings,
        secrets_type=ExampleSecrets,
        environ=environ
        if environ is not None
        else {
            "HIVE_USERNAME": "resolved-username-sentinel",
            "HIVE_PASSWORD": "resolved-password-sentinel",
        },
    )


def test_yaml_and_json_load_equivalent_versioned_configuration(tmp_path: Path) -> None:
    document = _valid_document()
    yaml_path = _write_yaml(
        tmp_path / "config.yaml",
        """
version: 1
plugin: hive
settings:
  host: hive.example.internal
  port: 10000
  tls: false
secrets:
  username: HIVE_USERNAME
  password: HIVE_PASSWORD
""".lstrip(),
    )
    json_path = _write_json(tmp_path / "config.json", document)

    yaml_config = _load(yaml_path)
    json_config = _load(json_path)

    assert yaml_config.version == json_config.version == 1
    assert yaml_config.plugin == json_config.plugin == "hive"
    assert (
        yaml_config.settings
        == json_config.settings
        == ExampleSettings(host="hive.example.internal", port=10_000, tls=False)
    )
    assert yaml_config.secrets.username.get_secret_value() == "resolved-username-sentinel"
    assert json_config.secrets.password.get_secret_value() == "resolved-password-sentinel"


def test_unsupported_version_is_identified_as_config_error(tmp_path: Path) -> None:
    document = _valid_document()
    document["version"] = 2

    with pytest.raises(ConfigError) as exc_info:
        _load(_write_json(tmp_path / "config.json", document))

    assert exc_info.value.category == "CONFIG_ERROR"
    assert "unsupported configuration version 2" in str(exc_info.value)


def test_yaml_uses_safe_loader_and_does_not_construct_objects(tmp_path: Path) -> None:
    marker = tmp_path / "unsafe-loader-was-used"
    config_path = _write_yaml(
        tmp_path / "config.yaml",
        f"""
version: 1
plugin: hive
settings:
  host: hive.example.internal
secrets:
  username: HIVE_USERNAME
  password: !!python/object/apply:os.system ["touch {marker}"]
""".lstrip(),
    )

    with pytest.raises(ConfigError) as exc_info:
        _load(config_path)

    assert exc_info.value.category == "CONFIG_ERROR"
    assert not marker.exists()


@pytest.mark.parametrize(
    ("section", "field"),
    [
        (None, "unexpected_root"),
        ("settings", "unexpected_setting"),
        ("secrets", "unexpected_secret"),
    ],
)
def test_unknown_fields_are_rejected(tmp_path: Path, section: str | None, field: str) -> None:
    document = _valid_document()
    if section is None:
        document[field] = "not allowed"
    else:
        nested = document[section]
        assert isinstance(nested, dict)
        nested[field] = "not allowed"

    with pytest.raises(ConfigError) as exc_info:
        _load(_write_json(tmp_path / "config.json", document))

    assert exc_info.value.category == "CONFIG_ERROR"
    assert field in str(exc_info.value)


def test_unknown_fields_in_nested_models_are_rejected(tmp_path: Path) -> None:
    document = _valid_document()
    document["settings"] = {
        "connection": {
            "endpoint": "service.example.internal",
            "nested_extra": 1,
        }
    }
    config_path = _write_json(tmp_path / "config.json", document)

    with pytest.raises(ConfigError) as exc_info:
        load_config(
            config_path,
            expected_plugin="hive",
            settings_type=SettingsWithNestedModel,
            secrets_type=ExampleSecrets,
            environ={
                "HIVE_USERNAME": "resolved-username-sentinel",
                "HIVE_PASSWORD": "resolved-password-sentinel",
            },
        )

    assert "settings.connection.nested_extra" in str(exc_info.value)


def test_valid_open_mapping_branch_in_model_union_is_accepted(tmp_path: Path) -> None:
    document = _valid_document()
    document["settings"] = {"connection": {"freeform": 1}}
    config_path = _write_json(tmp_path / "config.json", document)

    loaded = load_config(
        config_path,
        expected_plugin="hive",
        settings_type=SettingsWithModelOrMapping,
        secrets_type=ExampleSecrets,
        environ={
            "HIVE_USERNAME": "resolved-username-sentinel",
            "HIVE_PASSWORD": "resolved-password-sentinel",
        },
    )

    assert loaded.settings.connection == {"freeform": 1}


def test_cli_plugin_must_match_file_plugin(tmp_path: Path) -> None:
    document = _valid_document()
    document["plugin"] = "zeppelin"

    with pytest.raises(ConfigError) as exc_info:
        _load(_write_json(tmp_path / "config.json", document))

    assert exc_info.value.category == "CONFIG_ERROR"
    assert "does not match" in str(exc_info.value)


def test_supported_non_sensitive_environment_overrides_are_typed(tmp_path: Path) -> None:
    config_path = _write_json(tmp_path / "config.json", _valid_document())
    environ = {
        "HIVE_USERNAME": "resolved-username-sentinel",
        "HIVE_PASSWORD": "resolved-password-sentinel",
        "MCP_STDIO__SETTINGS__PORT": "10001",
        "MCP_STDIO__SETTINGS__TLS": "true",
    }

    loaded = _load(config_path, environ)

    assert loaded.settings.port == 10_001
    assert loaded.settings.tls is True


def test_invalid_environment_override_is_a_safe_config_error(tmp_path: Path) -> None:
    config_path = _write_json(tmp_path / "config.json", _valid_document())
    environ = {
        "HIVE_USERNAME": "resolved-username-sentinel",
        "HIVE_PASSWORD": "resolved-password-sentinel",
        "MCP_STDIO__SETTINGS__PORT": "not-a-port",
    }

    with pytest.raises(ConfigError) as exc_info:
        _load(config_path, environ)

    assert exc_info.value.category == "CONFIG_ERROR"
    assert "settings.port" in str(exc_info.value)
    assert "resolved-password-sentinel" not in str(exc_info.value)


def test_file_setting_types_are_not_coerced(tmp_path: Path) -> None:
    document = _valid_document()
    settings = document["settings"]
    assert isinstance(settings, dict)
    settings["port"] = "10000"

    with pytest.raises(ConfigError) as exc_info:
        _load(_write_json(tmp_path / "config.json", document))

    assert exc_info.value.category == "CONFIG_ERROR"
    assert "settings.port" in str(exc_info.value)


def test_secret_references_resolve_to_masked_values(tmp_path: Path) -> None:
    loaded = _load(_write_json(tmp_path / "config.json", _valid_document()))

    assert loaded.secrets.password.get_secret_value() == "resolved-password-sentinel"
    assert "resolved-password-sentinel" not in repr(loaded)


def test_unsafe_plain_string_secret_schema_is_rejected_before_resolution(tmp_path: Path) -> None:
    secret_sentinel = "unsafe-schema-secret-sentinel"
    document = _valid_document()
    document["secrets"] = {"password": "PASSWORD_ENV"}
    config_path = _write_json(tmp_path / "config.json", document)

    with pytest.raises(ConfigError) as exc_info:
        load_config(
            config_path,
            expected_plugin="hive",
            settings_type=ExampleSettings,
            secrets_type=UnsafeSecrets,
            environ={"PASSWORD_ENV": secret_sentinel},
        )

    rendered_error = "".join(traceback.format_exception(exc_info.value))
    assert secret_sentinel not in rendered_error


def test_optional_safe_secret_types_are_supported_and_masked(tmp_path: Path) -> None:
    secret_sentinel = "optional-auth-secret-sentinel"
    document = _valid_document()
    document["secrets"] = {"token": "TOKEN_ENV"}
    config_path = _write_json(tmp_path / "config.json", document)

    loaded = load_config(
        config_path,
        expected_plugin="hive",
        settings_type=ExampleSettings,
        secrets_type=OptionalAuthSecrets,
        environ={"TOKEN_ENV": secret_sentinel},
    )

    assert loaded.secrets.token is not None
    assert loaded.secrets.token.get_secret_value() == secret_sentinel
    assert secret_sentinel not in repr(loaded.secrets)


def test_secret_bytes_schema_is_rejected_before_resolution(tmp_path: Path) -> None:
    secret_sentinel = "byte-secret-sentinel"
    document = _valid_document()
    document["secrets"] = {"certificate": "CERTIFICATE_ENV"}
    config_path = _write_json(tmp_path / "config.json", document)

    with pytest.raises(ConfigError) as exc_info:
        load_config(
            config_path,
            expected_plugin="hive",
            settings_type=ExampleSettings,
            secrets_type=ByteSecrets,
            environ={"CERTIFICATE_ENV": secret_sentinel},
        )

    rendered_traceback = "".join(traceback.format_exception(exc_info.value))
    assert "must use SecretStr" in rendered_traceback
    assert secret_sentinel not in rendered_traceback


def test_typing_optional_safe_secret_type_is_supported(tmp_path: Path) -> None:
    document = _valid_document()
    document["secrets"] = {"token": "TOKEN_ENV"}
    config_path = _write_json(tmp_path / "config.json", document)

    loaded = load_config(
        config_path,
        expected_plugin="hive",
        settings_type=ExampleSettings,
        secrets_type=LegacyOptionalAuthSecrets,
        environ={"TOKEN_ENV": "legacy-optional-secret-sentinel"},
    )

    assert loaded.secrets.token is not None


def test_missing_secret_names_variable_without_exposing_other_values(tmp_path: Path) -> None:
    config_path = _write_json(tmp_path / "config.json", _valid_document())
    environ = {
        "HIVE_USERNAME": "resolved-username-sentinel",
        "UNRELATED_SECRET": "must-not-appear-sentinel",
    }

    with pytest.raises(ConfigError) as exc_info:
        _load(config_path, environ)

    error = str(exc_info.value)
    assert exc_info.value.category == "CONFIG_ERROR"
    assert "HIVE_PASSWORD" in error
    assert "resolved-username-sentinel" not in error
    assert "must-not-appear-sentinel" not in error


def test_literal_secret_object_is_rejected_without_echoing_it(tmp_path: Path) -> None:
    document = _valid_document()
    secrets = document["secrets"]
    assert isinstance(secrets, dict)
    secrets["password"] = {"value": "literal-secret-sentinel"}

    with pytest.raises(ConfigError) as exc_info:
        _load(_write_json(tmp_path / "config.json", document))

    error = str(exc_info.value)
    assert exc_info.value.category == "CONFIG_ERROR"
    assert "secrets.password" in error
    assert "literal-secret-sentinel" not in error


def test_parser_error_traceback_does_not_echo_file_content(tmp_path: Path) -> None:
    secret_sentinel = "parser-secret-sentinel"
    config_path = _write_yaml(
        tmp_path / "config.yaml",
        f"""
version: 1
plugin: hive
settings:
  host: hive.example.internal
secrets:
  username: HIVE_USERNAME
  password: [{secret_sentinel}
""".lstrip(),
    )

    with pytest.raises(ConfigError) as exc_info:
        _load(config_path)

    rendered_traceback = "".join(traceback.format_exception(exc_info.value))
    assert secret_sentinel not in rendered_traceback


def test_secret_validation_traceback_does_not_echo_resolved_value(tmp_path: Path) -> None:
    secret_sentinel = "short-secret-sentinel"
    config_path = _write_json(tmp_path / "config.json", _valid_document())

    with pytest.raises(ConfigError) as exc_info:
        load_config(
            config_path,
            expected_plugin="hive",
            settings_type=ExampleSettings,
            secrets_type=LengthCheckedSecrets,
            environ={
                "HIVE_USERNAME": "resolved-username-sentinel",
                "HIVE_PASSWORD": secret_sentinel,
            },
        )

    rendered_traceback = "".join(traceback.format_exception(exc_info.value))
    assert secret_sentinel not in rendered_traceback


def test_non_validation_error_from_validator_is_mapped_without_secret(tmp_path: Path) -> None:
    secret_sentinel = "validator-secret-sentinel"
    document = _valid_document()
    document["secrets"] = {"password": "PASSWORD_ENV"}
    config_path = _write_json(tmp_path / "config.json", document)

    with pytest.raises(ConfigError) as exc_info:
        load_config(
            config_path,
            expected_plugin="hive",
            settings_type=ExampleSettings,
            secrets_type=ExplodingValidatorSecrets,
            environ={"PASSWORD_ENV": secret_sentinel},
        )

    rendered_traceback = "".join(traceback.format_exception(exc_info.value))
    assert secret_sentinel not in rendered_traceback


def test_configuration_loading_performs_no_network_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_network(*_args: object, **_kwargs: object) -> None:
        pytest.fail("configuration loading attempted a network connection")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    monkeypatch.setattr(socket.socket, "connect", fail_network)

    loaded = _load(_write_json(tmp_path / "config.json", _valid_document()))

    assert loaded.settings.host == "hive.example.internal"


def test_unsupported_file_extension_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("version = 1", encoding="utf-8")

    with pytest.raises(ConfigError) as exc_info:
        _load(config_path)

    assert exc_info.value.category == "CONFIG_ERROR"
    assert ".toml" in str(exc_info.value)
