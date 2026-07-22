"""Shared configuration loading and secret resolution."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Generic, Literal, TypeVar, cast

import yaml
from pydantic import BaseModel, TypeAdapter, ValidationError

_SUPPORTED_VERSION = 1
_ROOT_FIELDS = frozenset({"version", "plugin", "settings", "secrets"})
_SETTINGS_OVERRIDE_PREFIX = "MCP_STDIO__SETTINGS__"
_ENVIRONMENT_VARIABLE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")

SettingsT = TypeVar("SettingsT", bound=BaseModel)
SecretsT = TypeVar("SecretsT", bound=BaseModel)


class ConfigError(ValueError):
    """A configuration failure whose message is safe to show to a user."""

    category: ClassVar[str] = "CONFIG_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(f"{self.category}: {message}")


@dataclass(frozen=True, slots=True)
class LoadedConfig(Generic[SettingsT, SecretsT]):
    """A validated configuration with resolved, non-repr secret values."""

    version: Literal[1]
    plugin: str
    settings: SettingsT
    secrets: SecretsT = field(repr=False)


def load_config(
    path: str | Path,
    *,
    expected_plugin: str,
    settings_type: type[SettingsT],
    secrets_type: type[SecretsT],
    environ: Mapping[str, str] | None = None,
) -> LoadedConfig[SettingsT, SecretsT]:
    """Load and validate one plugin's local configuration without network access."""

    config_path = Path(path)
    document = _read_document(config_path)
    root = _require_string_mapping(document, location="configuration root")
    _reject_unknown_fields(root, allowed=_ROOT_FIELDS, location="configuration root")

    version = root.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ConfigError("configuration version must be an integer")
    if version != _SUPPORTED_VERSION:
        raise ConfigError(f"unsupported configuration version {version}")

    plugin = root.get("plugin")
    if not isinstance(plugin, str) or not plugin:
        raise ConfigError("plugin must be a non-empty string")
    if plugin != expected_plugin:
        raise ConfigError(
            f"configuration plugin {plugin!r} does not match selected plugin {expected_plugin!r}"
        )

    raw_settings = _require_string_mapping(root.get("settings"), location="settings")
    _reject_unknown_model_fields(raw_settings, settings_type, location="settings")
    settings_data = dict(raw_settings)
    environment = os.environ if environ is None else environ
    _apply_settings_overrides(settings_data, settings_type, environment)
    settings = _validate_model(settings_type, settings_data, location="settings")

    raw_secret_references = _require_string_mapping(root.get("secrets"), location="secrets")
    _reject_unknown_model_fields(raw_secret_references, secrets_type, location="secrets")
    resolved_secrets = _resolve_secret_references(raw_secret_references, environment)
    secrets = _validate_model(secrets_type, resolved_secrets, location="secrets")

    return LoadedConfig(version=1, plugin=plugin, settings=settings, secrets=secrets)


def _read_document(path: Path) -> object:
    suffix = path.suffix.lower()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise ConfigError(f"could not read configuration file {path}") from None

    try:
        if suffix in {".yaml", ".yml"}:
            return cast(object, yaml.safe_load(text))
        if suffix == ".json":
            return cast(object, json.loads(text))
    except (json.JSONDecodeError, yaml.YAMLError):
        raise ConfigError(f"could not parse configuration file {path}") from None

    raise ConfigError(f"unsupported configuration file extension {suffix!r}")


def _require_string_mapping(value: object, *, location: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ConfigError(f"{location} must be an object")

    result: dict[str, object] = {}
    for key, item in cast(Mapping[object, object], value).items():
        if not isinstance(key, str):
            raise ConfigError(f"{location} contains a non-string field name")
        result[key] = item
    return result


def _reject_unknown_fields(
    values: Mapping[str, object], *, allowed: frozenset[str], location: str
) -> None:
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ConfigError(f"unknown field {location}.{unknown[0]}")


def _reject_unknown_model_fields(
    values: Mapping[str, object], model_type: type[BaseModel], *, location: str
) -> None:
    allowed = frozenset(model_type.model_fields)
    _reject_unknown_fields(values, allowed=allowed, location=location)


def _apply_settings_overrides(
    settings: dict[str, object],
    settings_type: type[BaseModel],
    environ: Mapping[str, str],
) -> None:
    for field_name, model_field in settings_type.model_fields.items():
        environment_name = f"{_SETTINGS_OVERRIDE_PREFIX}{field_name.upper()}"
        if environment_name in environ:
            settings[field_name] = _parse_environment_override(
                environ[environment_name], annotation=model_field.annotation
            )


def _parse_environment_override(value: str, *, annotation: object) -> object:
    adapter: TypeAdapter[object] = TypeAdapter(annotation)
    try:
        return adapter.validate_json(value, strict=True)
    except ValidationError:
        try:
            return adapter.validate_python(value, strict=True)
        except ValidationError:
            return value


def _resolve_secret_references(
    references: Mapping[str, object], environ: Mapping[str, str]
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for field_name, reference in references.items():
        location = f"secrets.{field_name}"
        if not isinstance(reference, str) or not _ENVIRONMENT_VARIABLE_NAME.fullmatch(reference):
            raise ConfigError(f"{location} must contain an environment variable name")
        if reference not in environ:
            raise ConfigError(f"required environment variable {reference} is not set")
        resolved[field_name] = environ[reference]
    return resolved


def _validate_model(
    model_type: type[SettingsT], values: Mapping[str, object], *, location: str
) -> SettingsT:
    try:
        return model_type.model_validate(values, strict=True)
    except ValidationError as error:
        invalid_locations = sorted(
            {
                ".".join((location, *(str(part) for part in detail["loc"])))
                for detail in error.errors(include_input=False, include_url=False)
            }
        )
        invalid_location = invalid_locations[0] if invalid_locations else location
        raise ConfigError(f"invalid configuration at {invalid_location}") from None
