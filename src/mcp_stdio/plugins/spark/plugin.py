"""Spark composition and owned resource lifecycle."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from mcp_stdio.contracts.plugin import (
    BuiltinPluginName,
    PluginDefinition,
    PluginRuntime,
    ToolRegistrar,
)
from mcp_stdio.core.config import load_config
from mcp_stdio.plugins.spark.cache import SparkEventLogAdapter
from mcp_stdio.plugins.spark.config import SparkSecrets, SparkSettings
from mcp_stdio.plugins.spark.files import credential_values
from mcp_stdio.plugins.spark.gateway import SparkEventLogGateway, SparkInspectionGateway
from mcp_stdio.plugins.spark.inspection import SparkInspectionAdapter
from mcp_stdio.plugins.spark.service import (
    SparkEventLogService,
    SparkInspectionService,
    SparkMetricsService,
)
from mcp_stdio.plugins.spark.tools import SparkToolAdapter


class SparkRuntime:
    def __init__(
        self,
        tools: SparkToolAdapter,
        gateway: SparkEventLogGateway,
        redaction_values: tuple[str, ...],
        *,
        inspection_gateway: SparkInspectionGateway | None = None,
    ) -> None:
        self._tools = tools
        self._gateway = gateway
        self._inspection_gateway = inspection_gateway
        self._secrets = redaction_values
        self._closed = False

    @property
    def name(self) -> BuiltinPluginName:
        return "spark"

    @property
    def redaction_values(self) -> tuple[str, ...]:
        return self._secrets

    def register_tools(self, registrar: ToolRegistrar) -> None:
        self._tools.register_tools(registrar)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._inspection_gateway is not None:
                await self._inspection_gateway.close()
        finally:
            await self._gateway.close()


def _create_runtime(config_path: Path | None, environ: Mapping[str, str] | None) -> PluginRuntime:
    loaded = load_config(
        config_path,
        expected_plugin="spark",
        settings_type=SparkSettings,
        secrets_type=SparkSecrets,
        environ=environ,
        env_prefix="SPARK",
    )
    gateway = SparkEventLogAdapter(settings=loaded.settings, secrets=loaded.secrets)
    service = SparkEventLogService(
        gateway=gateway, request_timeout_seconds=loaded.settings.request_timeout_seconds
    )
    values = credential_values(loaded.secrets.redaction_values)
    inspector = SparkInspectionAdapter(loaded.settings, values)
    inspection_service = SparkInspectionService(
        gateway=inspector, request_timeout_seconds=loaded.settings.request_timeout_seconds
    )
    metrics_service = SparkMetricsService(
        gateway=inspector, request_timeout_seconds=loaded.settings.request_timeout_seconds
    )
    return SparkRuntime(
        SparkToolAdapter(
            service=service,
            inspection_service=inspection_service,
            metrics_service=metrics_service,
            secret_values=values,
        ),
        gateway,
        values,
        inspection_gateway=inspector,
    )


PLUGIN_DEFINITION = PluginDefinition(name="spark", runtime_builder=_create_runtime)
