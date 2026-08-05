"""Zeppelin plugin composition boundary."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from mcp_stdio.contracts.plugin import (
    BuiltinPluginName,
    PluginDefinition,
    PluginRuntime,
    ToolRegistrar,
)
from mcp_stdio.core.config import load_config
from mcp_stdio.plugins.zeppelin.config import ZeppelinSecrets, ZeppelinSettings
from mcp_stdio.plugins.zeppelin.http_client import ZeppelinHttpClient
from mcp_stdio.plugins.zeppelin.safety import build_default_safety_hook
from mcp_stdio.plugins.zeppelin.service import ZeppelinNotebookService
from mcp_stdio.plugins.zeppelin.tools import ZeppelinToolAdapter


class ZeppelinRuntime:
    """Locally composed Zeppelin runtime with one lazy HTTP client per process."""

    def __init__(
        self,
        tools: ZeppelinToolAdapter,
        gateway: ZeppelinHttpClient,
        *,
        redaction_values: Iterable[str] = (),
    ) -> None:
        self._tools = tools
        self._gateway = gateway
        self._redaction_values = tuple(value for value in redaction_values if value)
        self._closed = False

    @property
    def name(self) -> BuiltinPluginName:
        return "zeppelin"

    @property
    def redaction_values(self) -> tuple[str, ...]:
        return self._redaction_values

    def register_tools(self, registrar: ToolRegistrar) -> None:
        self._tools.register_tools(registrar)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._gateway.close()


def _secret_values(secrets: ZeppelinSecrets) -> tuple[str, ...]:
    values: list[str] = []
    if secrets.username is not None:
        values.append(secrets.username.get_secret_value())
    if secrets.password is not None:
        values.append(secrets.password.get_secret_value())
    return tuple(values)


def _create_runtime(
    config_path: Path | None,
    environ: Mapping[str, str] | None,
) -> PluginRuntime:
    loaded = load_config(
        config_path,
        expected_plugin="zeppelin",
        settings_type=ZeppelinSettings,
        secrets_type=ZeppelinSecrets,
        environ=environ,
        env_prefix="ZEPPELIN",
    )
    gateway = ZeppelinHttpClient(settings=loaded.settings, secrets=loaded.secrets)
    safety_hook = build_default_safety_hook(
        allowed_interpreters=loaded.settings.allowed_interpreters,
        sql_forbidden_keywords=loaded.settings.sql_forbidden_keywords,
        sql_write_allowed_databases=loaded.settings.sql_write_allowed_databases,
        sh_allowed_commands=loaded.settings.sh_allowed_commands,
    )
    service = ZeppelinNotebookService(
        gateway=gateway,
        safety_hook=safety_hook,
        restartable_interpreter_settings=loaded.settings.restartable_interpreter_settings,
        max_notebook_name_chars=loaded.settings.max_notebook_name_chars,
        max_paragraph_title_chars=loaded.settings.max_paragraph_title_chars,
        max_paragraph_body_bytes=loaded.settings.max_paragraph_body_bytes,
        max_opaque_id_chars=loaded.settings.max_opaque_id_chars,
    )
    secrets = _secret_values(loaded.secrets)
    tools = ZeppelinToolAdapter(service=service, secret_values=secrets)
    return ZeppelinRuntime(tools, gateway, redaction_values=secrets)


PLUGIN_DEFINITION = PluginDefinition(name="zeppelin", runtime_builder=_create_runtime)
