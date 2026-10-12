# Spark event log download micro-plans

**Goal:** Implement the approved minimum download tool.
**Architecture:** Spark owns config, models, service/gateway and adapters. OpenSpec tasks.md is the sole progress checklist; these task-scoped notes are subordinate to its specs.
**Tech stack:** Python >=3.10, uv, existing httpx/pydantic/MCP, POSIX stdlib.
**Mode:** Inline executing-plans, chosen in preflight because the tasks share a serial download chain.

## Task 1.1 — Configuration and domain contracts

Files: create src/mcp_stdio/plugins/spark/{__init__,config,models,gateway}.py and tests/unit/plugins/spark/{test_config,test_models}.py; modify src/mcp_stdio/core/errors.py and tests/unit/core/test_errors.py.
Consumes load_config, StrictConfigModel, SecretConfigModel, ToolError.
Produces FetchRequest, SparkSettings, SparkSecrets, SparkEventLogFile/FetchResult and SparkEventLogGateway.lookup/download/close.

1. RED: tests exercise file/env precedence, strict identifiers and exact result fields. Run `uv run --locked pytest tests/unit/plugins/spark/test_config.py tests/unit/plugins/spark/test_models.py tests/unit/core/test_errors.py`. Expected failures: missing Spark module and missing operation.
2. GREEN: strict models and local HTTPS/path/CA validators:
```python
class FetchRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    application_id: str
    attempt_id: str | None = None
    refresh: bool = False
# Shared operation and identifier addition:
FETCH_SPARK_EVENT_LOG = "fetch_spark_event_log"
frozenset({"application_id", "attempt_id"})
```
Full-match ASCII identities and field bounds follow design.md; CA uses ssl.create_default_context(cafile=...) locally and credentials remain SecretStr.
3. VERIFY/REFACTOR: repeat the test command and run `uv run --locked ruff check src/mcp_stdio/plugins/spark tests/unit/plugins/spark tests/unit/core/test_errors.py`; expect all passing with no network.
4. COMMIT: `git add src/mcp_stdio/plugins/spark src/mcp_stdio/core/errors.py tests/unit/plugins/spark tests/unit/core/test_errors.py openspec/changes/add-spark-event-log-download`; `git commit -m "feat(spark): define event log download contracts"`.
Self-review 1.1: only shared contracts; HTTP and publication remain in later OpenSpec tasks.

## Task 2.1 — HTTPS receive adapter

Files: src/mcp_stdio/plugins/spark/http_client.py; tests/unit/plugins/spark/test_http_client.py.
Consumes SparkSettings/SparkSecrets and spark_error. Produces SparkHttpClient.receive(application_id, attempt_id, destination: Path, deadline: float) -> None and close().
1. RED: mock two exact GET paths and status mapping; stream size/timeout/cancel tests. Run `uv run --locked pytest tests/unit/plugins/spark/test_http_client.py --tb=short -q`; expected missing HTTP adapter failures.
2. GREEN: construct lazy client with explicit TLS, never redirects/proxies; receive actual raw chunks under remaining deadline:
```python
suppress_http_transport_logging()
client = httpx.AsyncClient(verify=context, trust_env=False, follow_redirects=False)
await asyncio.wait_for(receive_once(), timeout=deadline - time.monotonic())
# receive_once: status mapping; exclusive 0600 destination; aiter_raw(65536);
# count bytes, reject over max_bytes, inspect bounded prefix, close response.
```
Errors map to fixed domain categories, and finally deletes unsuccessful destination and clears the client's response cookie jar.
3. VERIFY: same test command; `uv run --locked ruff check src/mcp_stdio/plugins/spark/http_client.py tests/unit/plugins/spark/test_http_client.py`; expected pass.
4. COMMIT: `git add src/mcp_stdio/plugins/spark/http_client.py tests/unit/plugins/spark/test_http_client.py openspec/changes/add-spark-event-log-download`; `git commit -m "feat(spark): download bounded authenticated history archives"`.
Self-review 2.1: HTTP has no event interpretation or persistent cache behavior.
