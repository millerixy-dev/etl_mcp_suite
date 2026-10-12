"""Opt-in authenticated gateway download; no live log is committed."""

from __future__ import annotations

import asyncio
import os

import pytest

from mcp_stdio.core.config import load_config
from mcp_stdio.plugins.spark.cache import SparkEventLogAdapter
from mcp_stdio.plugins.spark.config import SparkSecrets, SparkSettings
from mcp_stdio.plugins.spark.service import SparkEventLogService

_REQUIRED = (
    "MCP_STDIO_SPARK_APPLICATION_ID",
    "SPARK_HISTORY_SERVER_URL",
    "SPARK_CACHE_DIR",
    "SPARK_GATEWAY_COOKIE",
)


@pytest.mark.integration
async def test_spark_download() -> None:
    if os.environ.get("MCP_STDIO_SPARK_INTEGRATION") != "1" or not all(
        os.environ.get(name) for name in _REQUIRED
    ):
        pytest.skip("requires explicit Spark integration opt-in and deployment settings")
    loaded = load_config(
        None,
        expected_plugin="spark",
        settings_type=SparkSettings,
        secrets_type=SparkSecrets,
        env_prefix="SPARK",
    )
    gateway = SparkEventLogAdapter(settings=loaded.settings, secrets=loaded.secrets)
    service = SparkEventLogService(
        gateway=gateway, request_timeout_seconds=loaded.settings.request_timeout_seconds
    )
    try:
        result = await service.fetch(
            os.environ["MCP_STDIO_SPARK_APPLICATION_ID"],
            os.environ.get("MCP_STDIO_SPARK_ATTEMPT_ID") or None,
            refresh=True,
        )
        assert not result.cache_hit
        assert await asyncio.to_thread(os.path.isfile, result.manifest_path)
        for file in result.files:
            assert await asyncio.to_thread(os.path.isfile, file.local_path)
    finally:
        await gateway.close()
