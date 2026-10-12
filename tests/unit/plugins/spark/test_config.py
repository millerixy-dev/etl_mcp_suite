"""Spark configuration contracts; all credentials here are synthetic."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_stdio.core.config import ConfigError, load_config


def _load(path: Path | None, env: dict[str, str]):
    from mcp_stdio.plugins.spark.config import SparkSecrets, SparkSettings

    return load_config(
        path,
        expected_plugin="spark",
        settings_type=SparkSettings,
        secrets_type=SparkSecrets,
        env_prefix="SPARK",
        environ=env,
    )


def test_file_env_precedence_and_cookie_privacy(tmp_path: Path) -> None:
    path = tmp_path / "spark.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "plugin": "spark",
                "settings": {
                    "history_server_url": "https://history.example/gateway/",
                    "cache_dir": str(tmp_path / "l3"),
                    "verify_tls": False,
                },
                "secrets": {"gateway_cookie": "COOKIE"},
            }
        )
    )
    loaded = _load(
        path,
        {
            "COOKIE": "session=synthetic-cookie",
            "MCP_STDIO__SETTINGS__MAX_BYTES": "2000",
            "SPARK_MAX_BYTES": "3000",
            "SPARK_VERIFY_TLS": "true",
        },
    )
    assert loaded.settings.history_server_url == "https://history.example/gateway"
    assert loaded.settings.max_bytes == 3000
    assert loaded.settings.verify_tls is True
    assert _load(path, {"COOKIE": "session=synthetic-cookie"}).settings.verify_tls is False
    assert loaded.secrets.gateway_cookie is not None
    assert "synthetic-cookie" not in repr(loaded)


def test_env_only_defaults(tmp_path: Path) -> None:
    loaded = _load(
        None,
        {"SPARK_HISTORY_SERVER_URL": "https://history.example", "SPARK_CACHE_DIR": str(tmp_path)},
    )
    assert loaded.settings.verify_tls is True
    assert loaded.settings.max_bytes == 268435456
    assert loaded.settings.request_timeout_seconds == 300
    assert loaded.secrets.gateway_cookie is None


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("HISTORY_SERVER_URL", "http://history.example"),
        ("HISTORY_SERVER_URL", "https://user:pass@history.example"),
        ("HISTORY_SERVER_URL", "https://history.example?x=1"),
        ("HISTORY_SERVER_URL", "https://history.example/#x"),
        ("HISTORY_SERVER_URL", "https://history.example/a/%2e%2e"),
        ("HISTORY_SERVER_URL", "https://history.example/\nb"),
        ("CACHE_DIR", "relative"),
        ("REQUEST_TIMEOUT_SECONDS", "0"),
        ("REQUEST_TIMEOUT_SECONDS", "901"),
        ("MAX_BYTES", "0"),
        ("VERIFY_TLS", "0"),
        ("VERIFY_TLS", "null"),
        ("VERIFY_TLS", "invalid"),
        ("GATEWAY_COOKIE", "session=synthetic\nsecret"),
        ("CA_BUNDLE_PATH", "/does-not-exist/spark-ca.pem"),
    ],
)
def test_invalid_configuration_is_safe(tmp_path: Path, key: str, value: str) -> None:
    env = {
        "SPARK_HISTORY_SERVER_URL": "https://history.example",
        "SPARK_CACHE_DIR": str(tmp_path),
        f"SPARK_{key}": value,
    }
    with pytest.raises(ConfigError) as error:
        _load(None, env)
    assert "synthetic" not in str(error.value)


def test_symlink_cache_root_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "link"
    root.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ConfigError):
        _load(
            None,
            {"SPARK_HISTORY_SERVER_URL": "https://history.example", "SPARK_CACHE_DIR": str(root)},
        )


def test_unknown_setting_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "spark.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "plugin": "spark",
                "settings": {
                    "history_server_url": "https://history.example",
                    "cache_dir": str(tmp_path),
                    "cache_policy": "offline",
                },
                "secrets": {},
            }
        )
    )
    with pytest.raises(ConfigError):
        _load(path, {})


@pytest.mark.parametrize("suffix", ["yaml", "json"])
def test_documented_example_loads_without_network(tmp_path: Path, suffix: str) -> None:
    path = Path(__file__).parents[4] / "docs" / "examples" / f"spark.{suffix}"
    loaded = _load(
        path,
        {"SPARK_CACHE_DIR": str(tmp_path), "SPARK_GATEWAY_COOKIE": "session=synthetic-example"},
    )
    assert loaded.settings.history_server_url.startswith("https://history.example.invalid")
    assert loaded.settings.request_timeout_seconds == 300
    assert loaded.settings.max_bytes == 268435456
    assert "synthetic-example" not in repr(loaded)


def test_explicit_env_disables_tls_verification(tmp_path: Path) -> None:
    loaded = _load(
        None,
        {
            "SPARK_HISTORY_SERVER_URL": "https://history.example",
            "SPARK_CACHE_DIR": str(tmp_path),
            "SPARK_VERIFY_TLS": "false",
        },
    )
    assert loaded.settings.verify_tls is False
