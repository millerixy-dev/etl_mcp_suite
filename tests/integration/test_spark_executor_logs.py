"""Explicit opt-in live stdout acquisition through the shipped stdio process."""

# ruff: noqa: ASYNC240 -- bounded independent verification of private evidence
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mcp_stdio.core.config import LoadedConfig, load_config
from mcp_stdio.plugins.spark.config import SparkSecrets, SparkSettings, validate_auth
from mcp_stdio.plugins.spark.executor_log_models import SparkExecutorLogFetchResult
from mcp_stdio.plugins.spark.files import credential_values

_REQUIRED = (
    "MCP_STDIO_SPARK_APPLICATION_ID",
    "MCP_STDIO_SPARK_ATTEMPT_ID",
    "MCP_STDIO_SPARK_EXECUTOR_ID",
    "SPARK_HISTORY_SERVER_URL",
    "SPARK_CACHE_DIR",
    "SPARK_EXECUTOR_LOG_NODE_MANAGER_PATH",
    "SPARK_EXECUTOR_LOG_ALLOWED_UPSTREAMS",
)


@pytest.mark.integration
async def test_spark_executor_stdout() -> None:
    env = dict(os.environ)
    has_auth = bool(env.get("SPARK_GATEWAY_COOKIE")) or all(
        env.get(name) for name in ("SPARK_USERNAME", "SPARK_PASSWORD", "SPARK_KNOX_SSO_URL")
    )
    if (
        env.get("MCP_STDIO_SPARK_EXECUTOR_LOG_INTEGRATION") != "1"
        or not all(env.get(name) for name in _REQUIRED)
        or not has_auth
    ):
        pytest.skip(
            "requires explicit executor-log opt-in, exact identity, log route and authentication"
        )
    loaded = load_config(
        None,
        expected_plugin="spark",
        settings_type=SparkSettings,
        secrets_type=SparkSecrets,
        env_prefix="SPARK",
        environ=env,
    )
    validate_auth(loaded.settings, loaded.secrets)
    await _run_stdout(env, loaded)


async def _run_stdout(
    environ: Mapping[str, str], loaded: LoadedConfig[SparkSettings, SparkSecrets]
) -> None:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "mcp_stdio", "--plugin", "spark"], env=dict(environ)
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(
            read,
            write,
            read_timeout_seconds=timedelta(seconds=loaded.settings.request_timeout_seconds + 30),
        ) as session:
            await session.initialize()
            reply = await session.call_tool(
                "fetch_spark_executor_log",
                arguments={
                    "application_id": environ["MCP_STDIO_SPARK_APPLICATION_ID"],
                    "attempt_id": environ["MCP_STDIO_SPARK_ATTEMPT_ID"],
                    "executor_id": environ["MCP_STDIO_SPARK_EXECUTOR_ID"],
                    "log_type": "stdout",
                },
            )
            if reply.isError or not reply.content or reply.content[0].type != "text":
                pytest.fail("executor-log stdio acquisition did not return successful evidence")
            result = SparkExecutorLogFetchResult.model_validate_json(reply.content[0].text)
            path, manifest = Path(result.local_path), Path(result.manifest_path)
            raw = path.read_bytes()
            manifest_raw = manifest.read_bytes()
            if any(
                secret.encode() in raw + manifest_raw
                for secret in credential_values(loaded.secrets.redaction_values)
            ):
                pytest.fail("protected credential found in acquired evidence")
            assert hashlib.sha256(raw).hexdigest() == result.sha256
            assert len(raw) == result.size_bytes
            body = json.loads(manifest_raw)
            assert all(body[key] == value for key, value in result.model_dump().items())
            assert body["source_kind"] in {"node_manager", "job_history"}
            for file in (path, manifest):
                assert not file.is_symlink() and stat.S_IMODE(file.stat().st_mode) == 0o600
            assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
