import pytest


@pytest.mark.integration
def test_integration_suite_is_opt_in() -> None:
    """Keep the integration marker exercised before live suites are added."""


@pytest.mark.parametrize("mode", ["discovery", "restart"])
@pytest.mark.parametrize(
    "missing",
    [
        "MCP_STDIO_ZEPPELIN_INTEGRATION",
        "MCP_STDIO_ZEPPELIN_BASE_URL",
        "MCP_STDIO_ZEPPELIN_USERNAME",
        "MCP_STDIO_ZEPPELIN_PASSWORD",
        "MCP_STDIO_ZEPPELIN_NOTEBOOK_ID",
    ],
)
async def test_missing_prerequisite_constructs_no_gateway(monkeypatch, mode, missing):
    from tests.integration import test_zeppelin_server as live

    for key, value in _ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv(missing)
    monkeypatch.setattr(live, "ZeppelinHttpClient", _forbidden_gateway, raising=False)
    entry = getattr(live, f"test_zeppelin_{mode}", None)
    assert entry is not None, "integration entrypoint missing"
    with pytest.raises(pytest.skip.Exception):
        await entry()


_ENV = {
    "MCP_STDIO_ZEPPELIN_INTEGRATION": "1",
    "MCP_STDIO_ZEPPELIN_BASE_URL": "https://zeppelin.example.invalid/api",
    "MCP_STDIO_ZEPPELIN_USERNAME": "synthetic-user",
    "MCP_STDIO_ZEPPELIN_PASSWORD": "synthetic-password",
    "MCP_STDIO_ZEPPELIN_NOTEBOOK_ID": "note/context",
    "MCP_STDIO_ZEPPELIN_RESTART_INTEGRATION": "1",
    "MCP_STDIO_ZEPPELIN_RESTART_SETTING_ID": "1 disposable/setting",
}


def _forbidden_gateway(**kwargs):
    pytest.fail("gateway constructed before complete opt-in")


@pytest.mark.parametrize(
    "key,value",
    [
        ("MCP_STDIO_ZEPPELIN_INTEGRATION", "0"),
        ("MCP_STDIO_ZEPPELIN_RESTART_INTEGRATION", "0"),
        ("MCP_STDIO_ZEPPELIN_RESTART_INTEGRATION", None),
        ("MCP_STDIO_ZEPPELIN_RESTART_INTEGRATION", "true"),
        ("MCP_STDIO_ZEPPELIN_RESTART_INTEGRATION", "2"),
        ("MCP_STDIO_ZEPPELIN_RESTART_INTEGRATION", ""),
        ("MCP_STDIO_ZEPPELIN_RESTART_SETTING_ID", ""),
    ],
)
async def test_restart_requires_separate_explicit_gate(monkeypatch, key, value):
    from tests.integration import test_zeppelin_server as live

    for name, setting in _ENV.items():
        monkeypatch.setenv(name, setting)
    if value is None:
        monkeypatch.delenv(key, raising=False)
    else:
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(live, "ZeppelinHttpClient", _forbidden_gateway, raising=False)
    entry = getattr(live, "test_zeppelin_restart", None)
    assert entry is not None, "restart entrypoint missing"
    with pytest.raises(pytest.skip.Exception):
        await entry()


@pytest.mark.parametrize("mode", ["discovery", "restart"])
@pytest.mark.parametrize("fails", [False, True])
async def test_opt_in_passes_exact_context_and_always_closes(monkeypatch, mode, fails):
    from mcp_stdio.plugins.zeppelin.models import RestartInterpreterResult
    from tests.integration import test_zeppelin_server as live

    for key, value in _ENV.items():
        monkeypatch.setenv(key, value)
    calls = []

    class FakeGateway:
        def __init__(self, *, settings, secrets):
            calls.append(("construct", settings.restartable_interpreter_settings))

        async def get_interpreter_bindings(self, notebook_id):
            calls.append(("discovery", notebook_id))
            if fails:
                raise RuntimeError("synthetic failure")
            return ()

        async def restart_interpreter(self, setting_id, notebook_id=None):
            calls.append(("restart", setting_id, notebook_id))
            if fails:
                raise RuntimeError("synthetic failure")
            return RestartInterpreterResult(
                setting_id=setting_id, name="disposable", group="spark", status="READY"
            )

        async def close(self):
            calls.append(("close",))

    monkeypatch.setattr(live, "ZeppelinHttpClient", FakeGateway, raising=False)
    entry = getattr(live, f"test_zeppelin_{mode}", None)
    assert entry is not None, "integration entrypoint missing"
    if fails:
        with pytest.raises(RuntimeError, match="synthetic failure"):
            await entry()
    else:
        await entry()
    expected = (
        ("discovery", "note/context")
        if mode == "discovery"
        else ("restart", "1 disposable/setting", "note/context")
    )
    assert calls == [
        ("construct", () if mode == "discovery" else ("1 disposable/setting",)),
        expected,
        ("close",),
    ]


@pytest.mark.parametrize(
    "missing",
    [
        "MCP_STDIO_SPARK_INTEGRATION",
        "MCP_STDIO_SPARK_APPLICATION_ID",
        "SPARK_HISTORY_SERVER_URL",
        "SPARK_CACHE_DIR",
        "SPARK_GATEWAY_COOKIE",
    ],
)
async def test_spark_missing_opt_in_constructs_no_gateway(monkeypatch, missing):
    from tests.integration import test_spark_server as live

    for key, value in {
        "MCP_STDIO_SPARK_INTEGRATION": "1",
        "MCP_STDIO_SPARK_APPLICATION_ID": "application_1_42",
        "SPARK_HISTORY_SERVER_URL": "https://history.example.invalid",
        "SPARK_CACHE_DIR": "/tmp/spark-test-integration",
        "SPARK_GATEWAY_COOKIE": "session=synthetic-cookie",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv(missing)
    monkeypatch.setattr(live, "SparkEventLogAdapter", _forbidden_gateway, raising=False)
    with pytest.raises(pytest.skip.Exception):
        await live.test_spark_download()


async def test_spark_basic_opt_in_reaches_gateway(monkeypatch, tmp_path):
    from tests.integration import test_spark_server as live

    for key in ("SPARK_GATEWAY_COOKIE", "SPARK_CA_BUNDLE_PATH"):
        monkeypatch.delenv(key, raising=False)
    for key, value in {
        "MCP_STDIO_SPARK_INTEGRATION": "1",
        "MCP_STDIO_SPARK_APPLICATION_ID": "application_1_42",
        "SPARK_HISTORY_SERVER_URL": "https://history.example.invalid",
        "SPARK_KNOX_SSO_URL": "https://history.example.invalid/gateway/knoxsso/api/v1/websso",
        "SPARK_CACHE_DIR": str(tmp_path),
        "SPARK_USERNAME": "synthetic-user",
        "SPARK_PASSWORD": "synthetic-password",
    }.items():
        monkeypatch.setenv(key, value)

    class ReachedGateway(Exception):
        pass

    def capture(**kwargs):
        assert kwargs["secrets"].password.get_secret_value() == "synthetic-password"
        raise ReachedGateway()

    monkeypatch.setattr(live, "SparkEventLogAdapter", capture)
    with pytest.raises(ReachedGateway):
        try:
            await live.test_spark_download()
        except pytest.skip.Exception:
            pytest.fail("complete Basic configuration must pass the opt-in gate")


_LOG_ENV = {
    "MCP_STDIO_SPARK_EXECUTOR_LOG_INTEGRATION": "1",
    "MCP_STDIO_SPARK_APPLICATION_ID": "application_1_42",
    "MCP_STDIO_SPARK_ATTEMPT_ID": "2",
    "MCP_STDIO_SPARK_EXECUTOR_ID": "driver",
    "SPARK_HISTORY_SERVER_URL": "https://history.example.invalid/gateway/test/sparkhistory",
    "SPARK_CACHE_DIR": "/tmp/spark-logs-opt-in-test",
    "SPARK_EXECUTOR_LOG_NODE_MANAGER_PATH": "/yarn/nodemanager/node",
    "SPARK_EXECUTOR_LOG_ALLOWED_UPSTREAMS": '["http://node.example.invalid:8042"]',
    "SPARK_GATEWAY_COOKIE": "session=synthetic-cookie",
}


@pytest.mark.parametrize("missing", list(_LOG_ENV))
async def test_executor_log_missing_prerequisite_never_starts_stdio(monkeypatch, missing):
    from tests.integration import test_spark_executor_logs as live

    for name in ("SPARK_USERNAME", "SPARK_PASSWORD", "SPARK_KNOX_SSO_URL"):
        monkeypatch.delenv(name, raising=False)
    for key, value in _LOG_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv(missing)

    def forbidden(*args, **kwargs):
        pytest.fail("stdio started without complete opt-in")

    monkeypatch.setattr(live, "_run_stdout", forbidden)
    with pytest.raises(pytest.skip.Exception):
        await live.test_spark_executor_stdout()


@pytest.mark.parametrize("flag", ["0", "true", "2", ""])
async def test_executor_log_requires_literal_opt_in(monkeypatch, flag):
    from tests.integration import test_spark_executor_logs as live

    for key, value in _LOG_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("MCP_STDIO_SPARK_EXECUTOR_LOG_INTEGRATION", flag)
    with pytest.raises(pytest.skip.Exception):
        await live.test_spark_executor_stdout()


async def test_executor_log_complete_basic_reaches_stdio(monkeypatch, tmp_path):
    from tests.integration import test_spark_executor_logs as live

    for key, value in _LOG_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("SPARK_GATEWAY_COOKIE")
    monkeypatch.delenv("SPARK_CA_BUNDLE_PATH", raising=False)
    monkeypatch.setenv("SPARK_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SPARK_USERNAME", "synthetic-user")
    monkeypatch.setenv("SPARK_PASSWORD", "synthetic-password")
    monkeypatch.setenv("SPARK_KNOX_SSO_URL", "https://history.example.invalid/gateway/sso")
    calls = []

    async def capture(environ, loaded):
        calls.append(
            (environ["MCP_STDIO_SPARK_EXECUTOR_ID"], loaded.secrets.password.get_secret_value())
        )

    monkeypatch.setattr(live, "_run_stdout", capture)
    await live.test_spark_executor_stdout()
    assert calls == [("driver", "synthetic-password")]
