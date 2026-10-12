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
