"""Opt-in Zeppelin lifecycle, binding discovery and contextual restart tests.

Skipped unless MCP_STDIO_ZEPPELIN_INTEGRATION=1 is set alongside
MCP_STDIO_ZEPPELIN_BASE_URL, MCP_STDIO_ZEPPELIN_USERNAME, and
MCP_STDIO_ZEPPELIN_PASSWORD. Uses a dedicated notebook namespace and an
explicitly allowed test interpreter. Proxy environment variables are cleared
internally because the test connects to an internal host directly.
Discovery also requires MCP_STDIO_ZEPPELIN_NOTEBOOK_ID. Restart additionally
requires MCP_STDIO_ZEPPELIN_RESTART_INTEGRATION=1 and
MCP_STDIO_ZEPPELIN_RESTART_SETTING_ID for an explicitly authorized disposable
target. These are test controls, not runtime configuration keys.
"""

from __future__ import annotations

import os
import uuid

import pytest

from mcp_stdio.plugins.zeppelin.config import ZeppelinSecrets, ZeppelinSettings
from mcp_stdio.plugins.zeppelin.http_client import ZeppelinHttpClient

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_REQUIRED = (
    "MCP_STDIO_ZEPPELIN_INTEGRATION",
    "MCP_STDIO_ZEPPELIN_BASE_URL",
    "MCP_STDIO_ZEPPELIN_USERNAME",
    "MCP_STDIO_ZEPPELIN_PASSWORD",
)


def _is_enabled() -> bool:
    return (
        all(os.environ.get(var) for var in _REQUIRED)
        and os.environ.get("MCP_STDIO_ZEPPELIN_INTEGRATION") == "1"
    )


_PROXY_VARS = (
    "ALL_PROXY",
    "all_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
    "NO_PROXY",
    "no_proxy",
)


def _require_opt_in(*, discovery: bool = False, restart: bool = False) -> None:
    if not _is_enabled():
        pytest.skip("set MCP_STDIO_ZEPPELIN_INTEGRATION=1 with base URL/username/password")
    if discovery and not os.environ.get("MCP_STDIO_ZEPPELIN_NOTEBOOK_ID"):
        pytest.skip("set MCP_STDIO_ZEPPELIN_NOTEBOOK_ID to a readable test notebook")
    if restart and (
        os.environ.get("MCP_STDIO_ZEPPELIN_RESTART_INTEGRATION") != "1"
        or not os.environ.get("MCP_STDIO_ZEPPELIN_RESTART_SETTING_ID")
    ):
        pytest.skip("explicitly opt in with a dedicated disposable restart setting")


def _binding_adapter(*, restart: bool = False) -> ZeppelinHttpClient:
    settings = ZeppelinSettings(
        base_url=os.environ["MCP_STDIO_ZEPPELIN_BASE_URL"],
        restartable_interpreter_settings=(
            (os.environ["MCP_STDIO_ZEPPELIN_RESTART_SETTING_ID"],) if restart else ()
        ),
        request_timeout_seconds=60,
    )
    secrets = ZeppelinSecrets(
        username=os.environ["MCP_STDIO_ZEPPELIN_USERNAME"],
        password=os.environ["MCP_STDIO_ZEPPELIN_PASSWORD"],
    )
    return ZeppelinHttpClient(settings=settings, secrets=secrets)


async def test_zeppelin_discovery() -> None:
    _require_opt_in(discovery=True)
    adapter = _binding_adapter()
    try:
        bindings = await adapter.get_interpreter_bindings(
            os.environ["MCP_STDIO_ZEPPELIN_NOTEBOOK_ID"]
        )
        assert isinstance(bindings, tuple)
        assert len({binding.setting_id for binding in bindings}) == len(bindings)
    finally:
        await adapter.close()


async def test_zeppelin_restart() -> None:
    # Operators must authorize this dedicated disposable target before enabling it.
    _require_opt_in(discovery=True, restart=True)
    adapter = _binding_adapter(restart=True)
    setting_id = os.environ["MCP_STDIO_ZEPPELIN_RESTART_SETTING_ID"]
    try:
        result = await adapter.restart_interpreter(
            setting_id, os.environ["MCP_STDIO_ZEPPELIN_NOTEBOOK_ID"]
        )
        assert result.setting_id == setting_id
        assert set(result.model_dump()) == {"setting_id", "name", "group", "status"}
    finally:
        await adapter.close()


@pytest.fixture(autouse=True)
def _clear_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear proxy env vars so httpx connects to the internal host directly."""
    for var in _PROXY_VARS:
        monkeypatch.delenv(var, raising=False)


async def test_complete_zeppelin_lifecycle() -> None:
    _require_opt_in()
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

        paragraph_id = await adapter.add_paragraph(notebook_id, "probe", "%sh\necho hello")
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
