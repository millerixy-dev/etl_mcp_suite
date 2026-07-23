"""Opt-in Zeppelin integration test for the complete create/add/run/status/result lifecycle.

Skipped unless MCP_STDIO_ZEPPELIN_INTEGRATION=1 is set alongside
MCP_STDIO_ZEPPELIN_BASE_URL, MCP_STDIO_ZEPPELIN_USERNAME, and
MCP_STDIO_ZEPPELIN_PASSWORD. Uses a dedicated notebook namespace and an
explicitly allowed test interpreter. Proxy environment variables are cleared
internally because the test connects to an internal host directly.
"""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = pytest.mark.asyncio

_REQUIRED = (
    "MCP_STDIO_ZEPPELIN_INTEGRATION",
    "MCP_STDIO_ZEPPELIN_BASE_URL",
    "MCP_STDIO_ZEPPELIN_USERNAME",
    "MCP_STDIO_ZEPPELIN_PASSWORD",
)


def _is_enabled() -> bool:
    return all(os.environ.get(var) for var in _REQUIRED) and os.environ.get(
        "MCP_STDIO_ZEPPELIN_INTEGRATION"
    ) == "1"


_PROXY_VARS = (
     "ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
     "HTTPS_PROXY", "https_proxy", "NO_PROXY", "no_proxy",
 )


pytestmark = pytest.mark.skipif(
    not _is_enabled(),
    reason="set MCP_STDIO_ZEPPELIN_INTEGRATION=1 with base_url/username/password to run",
)


@pytest.fixture(autouse=True)
def _clear_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
     """Clear proxy env vars so httpx connects to the internal host directly."""
     for var in _PROXY_VARS:
         monkeypatch.delenv(var, raising=False)


async def test_complete_zeppelin_lifecycle() -> None:
    from mcp_stdio.plugins.zeppelin.config import ZeppelinSecrets, ZeppelinSettings
    from mcp_stdio.plugins.zeppelin.http_client import ZeppelinHttpClient
    from mcp_stdio.plugins.zeppelin.models import ParagraphStatus

    settings = ZeppelinSettings(
        base_url=os.environ["MCP_STDIO_ZEPPELIN_BASE_URL"],
        allowed_interpreters=("sh",),
        request_timeout_seconds=60,
    )
    secrets = ZeppelinSecrets(
        username=os.environ["MCP_STDIO_ZEPPELIN_USERNAME"],
        password=os.environ["MCP_STDIO_ZEPPELIN_PASSWORD"],
    )
    adapter = ZeppelinHttpClient(settings=settings, secrets=secrets)

    notebook_name = f"mcp_integration_{uuid.uuid4().hex[:8]}"
    try:
        notebook_id = await adapter.create_notebook(notebook_name)
        assert notebook_id

        paragraph_id = await adapter.add_paragraph(notebook_id, "probe", "sh", "echo hello")
        assert paragraph_id

        run_status = await adapter.run_paragraph(notebook_id, paragraph_id)
        assert run_status in (ParagraphStatus.PENDING, ParagraphStatus.RUNNING)

        import asyncio

        status = ParagraphStatus.RUNNING
        for _ in range(30):
            status = await adapter.get_paragraph_status(notebook_id, paragraph_id)
            terminal = (
                ParagraphStatus.FINISHED,
                ParagraphStatus.ERROR,
                ParagraphStatus.CANCELLED,
            )
            if status in terminal:
                break
            await asyncio.sleep(2)

        assert status is ParagraphStatus.FINISHED

        result_status, outputs, error, truncated = await adapter.get_paragraph_result(
            notebook_id, paragraph_id
        )
        assert result_status is ParagraphStatus.FINISHED
        assert error is None
        assert len(outputs) >= 1
        assert "hello" in outputs[0].text
    finally:
        await adapter.close()
