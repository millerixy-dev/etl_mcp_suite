"""Hive configuration contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_stdio.core.config import ConfigError, LoadedConfig, load_config
from mcp_stdio.plugins.hive.config import HiveSecrets, HiveSettings


def _write_json(path: Path, document: object) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _write_yaml(path: Path) -> Path:
    path.write_text(
        """
version: 1
plugin: hive
settings:
  host: hive.example.internal
secrets:
  username: HIVE_USERNAME
  password: HIVE_PASSWORD
""".lstrip(),
        encoding="utf-8",
    )
    return path


def _document() -> dict[str, object]:
    return {
        "version": 1,
        "plugin": "hive",
        "settings": {"host": "hive.example.internal"},
        "secrets": {"username": "HIVE_USERNAME", "password": "HIVE_PASSWORD"},
    }


def _load(path: Path) -> LoadedConfig[HiveSettings, HiveSecrets]:
    return load_config(
        path,
        expected_plugin="hive",
        settings_type=HiveSettings,
        secrets_type=HiveSecrets,
        environ={"HIVE_USERNAME": "user-sentinel", "HIVE_PASSWORD": "password-sentinel"},
    )


def test_hive_yaml_and_json_load_with_safe_defaults_and_resolved_secrets(
    tmp_path: Path,
) -> None:
    yaml_config = _load(_write_yaml(tmp_path / "hive.yaml"))
    json_config = _load(_write_json(tmp_path / "hive.json", _document()))

    assert yaml_config.settings == json_config.settings == HiveSettings(
        host="hive.example.internal",
        port=10_000,
        database="default",
        cache_ttl_seconds=30,
    )
    assert yaml_config.secrets.username.get_secret_value() == "user-sentinel"
    assert json_config.secrets.password.get_secret_value() == "password-sentinel"
    assert "user-sentinel" not in repr(yaml_config)
    assert "password-sentinel" not in repr(yaml_config.secrets)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("host", ""),
        ("host", "   "),
        ("host", 123),
        ("port", 0),
        ("port", 65_536),
        ("port", "10000"),
        ("database", "sales data"),
        ("database", "sales.prod"),
        ("cache_ttl_seconds", -1),
        ("cache_ttl_seconds", "30"),
    ],
)
def test_hive_settings_reject_invalid_or_non_strict_values(
    tmp_path: Path, field: str, value: object
) -> None:
    document = _document()
    settings = document["settings"]
    assert isinstance(settings, dict)
    settings[field] = value

    with pytest.raises(ConfigError, match=rf"settings\.{field}"):
        _load(_write_json(tmp_path / "hive.json", document))


@pytest.mark.parametrize("section", ["settings", "secrets"])
def test_hive_configuration_rejects_unknown_plugin_fields(tmp_path: Path, section: str) -> None:
    document = _document()
    values = document[section]
    assert isinstance(values, dict)
    values["sql" if section == "settings" else "token"] = "not-approved"

    with pytest.raises(ConfigError, match="unknown field"):
        _load(_write_json(tmp_path / "hive.json", document))


def test_hive_configuration_rejects_non_reference_secret_values(tmp_path: Path) -> None:
    document = _document()
    document["secrets"] = {
        "username": {"literal": "not-an-environment-reference"},
        "password": "HIVE_PASSWORD",
    }

    with pytest.raises(ConfigError, match=r"secrets\.username"):
        _load(_write_json(tmp_path / "hive.json", document))


def test_hive_configuration_requires_exact_plugin_match(tmp_path: Path) -> None:
    document = _document()
    document["plugin"] = "zeppelin"

    with pytest.raises(ConfigError, match="does not match"):
        _load(_write_json(tmp_path / "hive.json", document))


def test_hive_schema_contains_only_approved_settings_and_secrets() -> None:
    assert set(HiveSettings.model_fields) == {
        "host",
        "port",
        "database",
        "cache_ttl_seconds",
    }
    assert set(HiveSecrets.model_fields) == {"username", "password"}
