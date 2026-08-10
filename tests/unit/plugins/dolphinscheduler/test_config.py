"""DolphinScheduler configuration contract tests."""

from __future__ import annotations

import json
import traceback
from pathlib import Path

import pytest

from mcp_stdio.core.config import ConfigError, LoadedConfig, load_config
from mcp_stdio.plugins.dolphinscheduler.config import (
    DolphinSchedulerSecrets,
    DolphinSchedulerSettings,
)


def _document() -> dict[str, object]:
    return {
        "version": 1,
        "plugin": "dolphinscheduler",
        "settings": {"base_url": "http://ds.example:12345/dolphinscheduler/"},
        "secrets": {},
    }


def _write_json(path: Path, document: object) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _write_yaml(path: Path) -> Path:
    path.write_text(
        """
version: 1
plugin: dolphinscheduler
settings:
  base_url: http://ds.example:12345/dolphinscheduler/
secrets: {}
""".lstrip(),
        encoding="utf-8",
    )
    return path


def _load(
    path: Path, environ: dict[str, str] | None = None
) -> LoadedConfig[DolphinSchedulerSettings, DolphinSchedulerSecrets]:
    return load_config(
        path,
        expected_plugin="dolphinscheduler",
        settings_type=DolphinSchedulerSettings,
        secrets_type=DolphinSchedulerSecrets,
        environ={} if environ is None else environ,
    )


def test_yaml_and_json_load_equivalent_defaults_without_authentication(
    tmp_path: Path,
) -> None:
    yaml_config = _load(_write_yaml(tmp_path / "dolphinscheduler.yaml"))
    json_config = _load(_write_json(tmp_path / "dolphinscheduler.json", _document()))

    expected = DolphinSchedulerSettings(base_url="http://ds.example:12345/dolphinscheduler")
    assert yaml_config.settings == json_config.settings == expected
    assert expected.status_path == "/monitor/masters"
    assert expected.request_timeout_seconds == 30.0
    assert expected.max_response_bytes == 1_048_576
    assert expected.max_detail_items == 100
    assert yaml_config.secrets.token is None


def test_configuration_resolves_optional_token(tmp_path: Path) -> None:
    document = _document()
    document["secrets"] = {"token": "DOLPHINSCHEDULER_TOKEN"}

    loaded = _load(
        _write_json(tmp_path / "dolphinscheduler.json", document),
        {"DOLPHINSCHEDULER_TOKEN": "token-sentinel"},
    )

    assert loaded.secrets.token is not None
    assert loaded.secrets.token.get_secret_value() == "token-sentinel"
    assert "token-sentinel" not in repr(loaded)
    assert "token-sentinel" not in repr(loaded.secrets)


def test_empty_secrets_is_valid_without_authentication(tmp_path: Path) -> None:
    loaded = _load(_write_json(tmp_path / "dolphinscheduler.json", _document()))

    assert loaded.secrets.token is None


def test_missing_token_environment_variable_fails_closed(tmp_path: Path) -> None:
    document = _document()
    document["secrets"] = {"token": "DOLPHINSCHEDULER_TOKEN"}

    with pytest.raises(ConfigError):
        _load(_write_json(tmp_path / "dolphinscheduler.json", document), {})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("base_url", "ftp://ds.example"),
        ("base_url", "http://user:pass@ds.example"),
        ("base_url", "http://ds.example/path?mode=unsafe"),
        ("base_url", "http://ds.example/path#fragment"),
        ("base_url", "/relative/path"),
        ("base_url", 123),
        ("status_path", "monitor/masters"),
        ("status_path", "/monitor/masters?x=1"),
        ("status_path", "/monitor/masters#frag"),
        ("status_path", 123),
        ("request_timeout_seconds", 0),
        ("request_timeout_seconds", 300.1),
        ("request_timeout_seconds", "30"),
        ("request_timeout_seconds", True),
        ("max_response_bytes", 0),
        ("max_response_bytes", 8_388_609),
        ("max_detail_items", 0),
        ("max_detail_items", 1_001),
        ("default_page_size", 0),
        ("default_page_size", 101),
        ("default_page_size", "10"),
        ("default_page_size", True),
        ("max_page_size", 0),
        ("max_page_size", 201),
        ("max_page_size", "100"),
        ("max_page_size", True),
        ("max_log_bytes", 0),
        ("max_log_bytes", 8_388_609),
        ("max_log_bytes", "1048576"),
        ("max_log_bytes", True),
    ],
)
def test_rejects_unsafe_configuration(tmp_path: Path, field: str, value: object) -> None:
    document = _document()
    settings = document["settings"]
    assert isinstance(settings, dict)
    settings[field] = value

    with pytest.raises(ConfigError) as exc_info:
        _load(_write_json(tmp_path / "dolphinscheduler.json", document))

    rendered = "".join(
        traceback.format_exception(
            type(exc_info.value), exc_info.value, exc_info.value.__traceback__
        )
    )
    assert "token-sentinel" not in rendered


def test_rejects_unknown_field(tmp_path: Path) -> None:
    document = _document()
    settings = document["settings"]
    assert isinstance(settings, dict)
    settings["unexpected_field"] = "value"

    with pytest.raises(ConfigError):
        _load(_write_json(tmp_path / "dolphinscheduler.json", document))


def test_status_path_custom_value_is_preserved(tmp_path: Path) -> None:
    document = _document()
    settings = document["settings"]
    assert isinstance(settings, dict)
    settings["status_path"] = "/monitor/workers"

    loaded = _load(_write_json(tmp_path / "dolphinscheduler.json", document))

    assert loaded.settings.status_path == "/monitor/workers"


def test_scheduling_defaults_when_omitted(tmp_path: Path) -> None:
    loaded = _load(_write_json(tmp_path / "dolphinscheduler.json", _document()))

    assert loaded.settings.default_page_size == 10
    assert loaded.settings.max_page_size == 100
    assert loaded.settings.max_log_bytes == 1_048_576


def test_scheduling_settings_accepted_with_custom_values(tmp_path: Path) -> None:
    document = _document()
    settings = document["settings"]
    assert isinstance(settings, dict)
    settings["default_page_size"] = 25
    settings["max_page_size"] = 150
    settings["max_log_bytes"] = 2_097_152

    loaded = _load(_write_json(tmp_path / "dolphinscheduler.json", document))

    assert loaded.settings.default_page_size == 25
    assert loaded.settings.max_page_size == 150
    assert loaded.settings.max_log_bytes == 2_097_152


def test_scheduling_settings_respond_to_env_prefix_overrides(tmp_path: Path) -> None:
    loaded = load_config(
        _write_json(tmp_path / "dolphinscheduler.json", _document()),
        expected_plugin="dolphinscheduler",
        settings_type=DolphinSchedulerSettings,
        secrets_type=DolphinSchedulerSecrets,
        environ={
            "DOLPHINSCHEDULER_DEFAULT_PAGE_SIZE": "20",
            "DOLPHINSCHEDULER_MAX_PAGE_SIZE": "200",
            "DOLPHINSCHEDULER_MAX_LOG_BYTES": "2097152",
        },
        env_prefix="DOLPHINSCHEDULER",
    )

    assert loaded.settings.default_page_size == 20
    assert loaded.settings.max_page_size == 200
    assert loaded.settings.max_log_bytes == 2_097_152
