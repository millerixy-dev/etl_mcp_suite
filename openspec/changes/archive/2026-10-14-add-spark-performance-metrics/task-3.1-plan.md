# Spark performance MCP wiring Implementation Plan

> Execution: serial task 3.1 via executing-plans. OpenSpec tasks.md is the sole progress checklist; this micro-plan deliberately has no additional checkboxes.

**Goal:** expose the two approved offline metrics tools with strict public contracts.

**Architecture:** SparkMetricsService validates DTOs and calls SparkMetricsGateway. Composition passes the existing inspector to both services and retains its existing single close owner. Tools reuse whole-result redaction and closed result validation.

**Tech Stack:** Python >=3.10, Pydantic, FastMCP, asyncio, uv.

## Global constraints

No new configuration, dependencies, network requests, persistence, root-cause rules, or changes to existing computation. Required nullable attempt_id and expected_sha256 remain explicit. Only application/attempt identifiers are allowed in operation-specific errors.

## Files and interfaces

- src/mcp_stdio/core/errors.py: two closed operations and identifier allowlists.
- src/mcp_stdio/plugins/spark/service.py: SparkMetricsService.stage_metrics(manifest_path, attempt_id, expected_sha256, **selection) -> SparkStageMetricsResult and task_distribution(...) -> SparkTaskDistributionResult.
- src/mcp_stdio/plugins/spark/tools.py: get_spark_stage_metrics(manifest_path, attempt_id, expected_sha256, stage_id=None, stage_attempt_id=None, limit=20); get_spark_task_distribution(manifest_path, attempt_id, expected_sha256, stage_id, stage_attempt_id, order_by="duration_ms", limit=20).
- src/mcp_stdio/plugins/spark/plugin.py: inject metrics_service with gateway=inspector, no additional lifecycle owner.
- Existing service/tools/plugin/core/stdio/architecture tests and import_rules.py: strict validation, numeric result, full redaction, exact tool set, aliases, shutdown and offline no-write restart.

## RED tests

Extend exact operation/tool assertions with both names. Add fake gateway methods that record requests and deadlines and raise a safe existing fetch error; assert the service remaps to the correct operation and rejects paired-ID/type/enum/extra failures before gateway calls:

```python
@pytest.mark.parametrize("method", ["stage_metrics", "task_distribution"])
async def test_metrics_service_timeout_awaits_cleanup(method):
    gateway = FakeMetricsGateway(delay=1)
    service = SparkMetricsService(gateway=gateway, request_timeout_seconds=0.01)
    with pytest.raises(SparkGatewayError) as error:
        await getattr(service, method)("/l3/manifest.json", None, "a" * 64,
                                     stage_id=1, stage_attempt_id=0)
    assert error.value.tool_error.category == ErrorCategory.TIMEOUT
    assert gateway.cleaned
```

Use actual stdio synthetic TaskEnd records with durations 100 and 900, input 100/200, shuffle 100/900; assert Stage total 300/1000 and Task p50/p95 100/900 plus physical-line refs on first run and network-forbidden restart. Capture file bytes/mtimes around all offline calls. Add package alias import forms for metrics and metrics_events.

Run RED: `UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/core/test_errors.py tests/unit/plugins/spark/test_service.py tests/unit/plugins/spark/test_tools.py tests/unit/plugins/spark/test_plugin.py tests/contract/test_spark_stdio.py tests/contract/test_architecture.py`.

## GREEN implementation

Each service method constructs its exact request, sets the operation, validates before creating the awaitable, and preserves one original deadline:

```python
deadline = time.monotonic() + self._timeout
try:
    return await asyncio.wait_for(
        self._gateway.stage_metrics(request, deadline=deadline),
        timeout=max(0, deadline - time.monotonic()),
    )
except asyncio.TimeoutError:
    raise _error(ErrorCategory.TIMEOUT, operation, retryable=True) from None
except SparkGatewayError as error:
    raise _remap(error, operation) from None
```

The distribution method uses TaskDistributionRequest and gateway.task_distribution identically. Cancellation remains uncaught so wait_for awaits its cleanup.

```python
metrics_service = SparkMetricsService(
    gateway=inspector, request_timeout_seconds=loaded.settings.request_timeout_seconds
)
registrar.add_tool(self.get_spark_stage_metrics, name="get_spark_stage_metrics")
registrar.add_tool(self.get_spark_task_distribution, name="get_spark_task_distribution")
```

Both tools call the service then `_inspection_result`, extended to the two exact result DTOs. Validate against the expected named result type rather than an arbitrary returned type; redact full public copies, then fail closed if any configured secret survives. Preserve old three tools.

## Refactor and verification

Keep duplication limited to the two straightforward typed service methods; do not introduce a generic metric framework. Extend source guards for direct/relative/package alias metrics imports. Fresh full task verification:

`UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/core/test_errors.py tests/unit/plugins/spark tests/contract/test_spark_stdio.py tests/contract/test_architecture.py tests/unit/test_registry.py`

Then sequential `UV_NO_EDITABLE=1 uv run --locked ruff check .` and `UV_NO_EDITABLE=1 uv run --locked pyright`. Record actual evidence in task-3.1-report.md. Commit only owned files; controlling agent reviews, verifies and gates tasks.md.

## Self-review

Coverage includes strict inputs, named outputs, each operation, redaction, original deadline, cancellation, same owner, cleanup order, aliases and real stdio offline numeric calls. Models/ports already exist and signatures were read. No competing checklist, placeholders or requirement gaps.
