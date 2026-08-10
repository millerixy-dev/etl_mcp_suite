"""DolphinScheduler plugin composition boundary."""

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
from mcp_stdio.plugins.dolphinscheduler.config import (
    DolphinSchedulerSecrets,
    DolphinSchedulerSettings,
)
from mcp_stdio.plugins.dolphinscheduler.http_client import DolphinSchedulerHttpClient
from mcp_stdio.plugins.dolphinscheduler.service import DolphinSchedulerStatusService
from mcp_stdio.plugins.dolphinscheduler.tools import DolphinSchedulerToolAdapter


class DolphinSchedulerRuntime:
    """Locally composed DolphinScheduler runtime with one lazy HTTP client per process."""

    def __init__(
        self,
        tools: DolphinSchedulerToolAdapter,
        gateway: DolphinSchedulerHttpClient,
        *,
        redaction_values: Iterable[str] = (),
    ) -> None:
        self._tools = tools
        self._gateway = gateway
        self._redaction_values = tuple(value for value in redaction_values if value)
        self._closed = False

    @property
    def name(self) -> BuiltinPluginName:
        return "dolphinscheduler"

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


def _secret_values(secrets: DolphinSchedulerSecrets) -> tuple[str, ...]:
    if secrets.token is None:
        return ()
    return (secrets.token.get_secret_value(),)


def _create_runtime(
    config_path: Path | None,
    environ: Mapping[str, str] | None,
) -> PluginRuntime:
    loaded = load_config(
        config_path,
        expected_plugin="dolphinscheduler",
        settings_type=DolphinSchedulerSettings,
        secrets_type=DolphinSchedulerSecrets,
        environ=environ,
        env_prefix="DOLPHINSCHEDULER",
    )
    gateway = DolphinSchedulerHttpClient(settings=loaded.settings, secrets=loaded.secrets)
    service = DolphinSchedulerStatusService(
        gateway=gateway,
        max_detail_items=loaded.settings.max_detail_items,
        default_page_size=loaded.settings.default_page_size,
        max_page_size=loaded.settings.max_page_size,
        max_log_bytes=loaded.settings.max_log_bytes,
    )
    secrets = _secret_values(loaded.secrets)
    tools = DolphinSchedulerToolAdapter(service=service, secret_values=secrets)
    return DolphinSchedulerRuntime(tools, gateway, redaction_values=secrets)


PLUGIN_DEFINITION = PluginDefinition(
    name="dolphinscheduler",
    runtime_builder=_create_runtime,
)
