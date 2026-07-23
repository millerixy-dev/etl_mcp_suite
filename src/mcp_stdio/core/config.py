"""Shared configuration loading and secret resolution."""

from __future__ import annotations

import json
import os
import re
import typing
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import UnionType
from typing import Annotated, ClassVar, Generic, Literal, TypeVar, cast, get_args, get_origin

import yaml
from pydantic import BaseModel, ConfigDict, SecretStr, TypeAdapter, ValidationError

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


class StrictConfigModel(BaseModel):
    """Base for configuration schemas that reject unknown fields."""

    model_config = ConfigDict(extra="forbid")


class SecretConfigModel(StrictConfigModel):
    """Base for secret schemas whose fields are safe in model representations."""


@dataclass(frozen=True, slots=True)
class LoadedConfig(Generic[SettingsT, SecretsT]):
    """A validated configuration with resolved, non-repr secret values."""

    version: Literal[1]
    plugin: str
    settings: SettingsT
    secrets: SecretsT = field(repr=False)


def load_config(
    path: str | Path | None,
    *,
    expected_plugin: str,
    settings_type: type[SettingsT],
    secrets_type: type[SecretsT],
    environ: Mapping[str, str] | None = None,
    env_prefix: str = "",
) -> LoadedConfig[SettingsT, SecretsT]:
    """Load and validate one plugin's local configuration without network access.

    When *path* is ``None`` the configuration is synthesized entirely from
    ``<env_prefix>_<FIELD>`` environment variables (environment-variable-only
    startup). When a path is supplied, environment variables override file
    values: ``<env_prefix>_<FIELD>`` takes precedence over
    ``MCP_STDIO__SETTINGS__<FIELD>`` for settings and over file secret
    references for secrets.
    """

    environment = os.environ if environ is None else environ
    env_only = path is None

    if env_only and not env_prefix:
        raise ConfigError("a configuration file or plugin environment variables are required")

    raw_settings: dict[str, object]
    raw_secret_references: dict[str, object]
    plugin = expected_plugin

    if path is not None:
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
                f"configuration plugin {plugin!r} does not match"
                f" selected plugin {expected_plugin!r}"
            )

        raw_settings = _require_string_mapping(root.get("settings"), location="settings")
        _validate_strict_model_schema(settings_type, location="settings")
        _reject_unknown_model_fields(raw_settings, settings_type, location="settings")

        raw_secret_references = _require_string_mapping(root.get("secrets"), location="secrets")
        _reject_unknown_model_fields(raw_secret_references, secrets_type, location="secrets")
    else:
        _validate_strict_model_schema(settings_type, location="settings")
        raw_settings = {}
        raw_secret_references = {}

    _validate_secret_model_schema(secrets_type)

    settings_data = dict(raw_settings)
    _apply_settings_overrides(settings_data, settings_type, environment)
    if env_prefix:
        _apply_prefix_overrides(
            settings_data,
            settings_type,
            environment,
            env_prefix,
            required=env_only,
        )
    settings = _validate_model(settings_type, settings_data, location="settings")

    resolved_secrets = _resolve_secret_references(raw_secret_references, environment)
    if env_prefix:
        _apply_secret_prefix_overrides(
            resolved_secrets,
            secrets_type,
            environment,
            env_prefix,
            required=env_only,
        )
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


def _is_model_type(annotation: object) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def _model_types_in_annotation(annotation: object) -> set[type[BaseModel]]:
    if _is_model_type(annotation):
        return {cast(type[BaseModel], annotation)}
    nested_types: set[type[BaseModel]] = set()
    for argument in cast(tuple[object, ...], get_args(annotation)):
        nested_types.update(_model_types_in_annotation(argument))
    return nested_types


def _validate_strict_model_schema(
    model_type: type[BaseModel],
    *,
    location: str,
    checked: set[type[BaseModel]] | None = None,
) -> None:
    checked_types: set[type[BaseModel]] = set() if checked is None else checked
    if model_type in checked_types:
        return
    checked_types.add(model_type)
    if not issubclass(model_type, StrictConfigModel):
        raise ConfigError(f"configuration schema {location} must inherit StrictConfigModel")
    for field_name, model_field in model_type.model_fields.items():
        for nested_type in _model_types_in_annotation(model_field.annotation):
            _validate_strict_model_schema(
                nested_type,
                location=f"{location}.{field_name}",
                checked=checked_types,
            )


def _validate_secret_model_schema(model_type: type[BaseModel]) -> None:
    if not issubclass(model_type, SecretConfigModel):
        raise ConfigError("configuration schema secrets must inherit SecretConfigModel")
    for field_name, model_field in model_type.model_fields.items():
        if not _is_safe_secret_annotation(model_field.annotation):
            raise ConfigError(f"secret schema field secrets.{field_name} must use SecretStr")


def _is_safe_secret_annotation(annotation: object) -> bool:
    if isinstance(annotation, type) and issubclass(annotation, SecretStr):
        return True

    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin is Annotated and arguments:
        return _is_safe_secret_annotation(arguments[0])
    if origin in (UnionType, typing.Union):
        secret_arguments = tuple(argument for argument in arguments if argument is not type(None))
        return bool(secret_arguments) and all(
            _is_safe_secret_annotation(argument) for argument in secret_arguments
        )
    return False


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


def _prefix_variable(prefix: str, field_name: str) -> str:
    return f"{prefix}_{field_name.upper()}"


def _apply_prefix_overrides(
    settings: dict[str, object],
    settings_type: type[BaseModel],
    environ: Mapping[str, str],
    prefix: str,
    *,
    required: bool,
) -> None:
    for field_name, model_field in settings_type.model_fields.items():
        environment_name = _prefix_variable(prefix, field_name)
        if environment_name in environ:
            settings[field_name] = _parse_environment_override(
                environ[environment_name], annotation=model_field.annotation
            )
        elif required and model_field.is_required() and field_name not in settings:
            raise ConfigError(f"required environment variable {environment_name} is not set")


def _apply_secret_prefix_overrides(
    secrets: dict[str, str],
    secrets_type: type[BaseModel],
    environ: Mapping[str, str],
    prefix: str,
    *,
    required: bool,
) -> None:
    for field_name, model_field in secrets_type.model_fields.items():
        environment_name = _prefix_variable(prefix, field_name)
        if environment_name in environ:
            secrets[field_name] = environ[environment_name]
        elif required and model_field.is_required() and field_name not in secrets:
            raise ConfigError(f"required environment variable {environment_name} is not set")


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
    except Exception:
        raise ConfigError(f"invalid configuration at {location}") from None
