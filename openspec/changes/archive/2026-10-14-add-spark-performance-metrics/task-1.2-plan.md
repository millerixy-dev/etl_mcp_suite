# Task 1.2 fixed metrics implementation plan

**Goal:** Pure extraction of six measurements, explicit reason classification, and nearest-rank distributions.
**Architecture:** New metrics_events module consumes existing immutable DTOs and task_reason. No scan, state, network or caller-defined expressions.
**Tech Stack:** Python >=3.10, standard library and existing Pydantic DTOs; uv locked.

1. Create tests/unit/plugins/spark/test_metrics.py with strict raw integer cases and complete/partial event projections. First assertion:
```python
def test_integer_accepts_zero_and_signed_64_max():
    assert metric_integer(0) == 0
    assert metric_integer(2**63 - 1) == 2**63 - 1
```
Run `UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/plugins/spark/test_metrics.py`; expected RED missing metrics_events module.

2. Create src/mcp_stdio/plugins/spark/metrics_events.py. Export metric_integer(value: object) -> int | None, task_metric_values(event: dict[str, object]) -> TaskMetricValues and METRIC_NAMES: tuple[MetricName, ...]. Shared raw rule:
```python
def metric_integer(value: object) -> int | None:
    return value if type(value) is int and 0 <= value <= 2**63 - 1 else None
```
Read only named objects/fields. Duration requires valid Launch/Finish, Finish>0 and Finish>=Launch; Shuffle requires both valid components, preserving Python integer sum. Run same command; expect extraction tests GREEN.

3. Add classification tests for explicit Success, explicit UNKNOWN/non-success and invalid/missing reasons; retry/speculative samples remain independent. Add empty/single/double and 20-value nearest-rank tests. Run same command; expected RED absent helpers. Implement task_outcome(event: dict[str, object]) -> Literal["success", "non_success", "unknown"] using existing task_reason validity. Implement metric_distribution(values: Sequence[int], successful_count: int) -> MetricDistribution, taking already validated samples:
```python
ordered = sorted(values)
n = len(ordered)
p50 = ordered[(50 * n + 99) // 100 - 1] if n else None
p95 = ordered[(95 * n + 99) // 100 - 1] if n else None
```
Count missing as successful_count-n; no interpolation or deduplication. Run same command, expect GREEN.

4. Self-review against design section 2 and sample/distribution scenarios; confirm all six names/order match DTOs, unknown remains null, booleans rejected and large Shuffle sums preserved. Run `uv run --locked ruff check src/mcp_stdio/plugins/spark/metrics_events.py tests/unit/plugins/spark/test_metrics.py` then `uv run --locked pyright src/mcp_stdio/plugins/spark/metrics_events.py tests/unit/plugins/spark/test_metrics.py`. Record exact results in task-1.2-report.md and commit these four owned files. Parent controls tasks.md and fresh whole-change verification.

Plan self-review: covers all task1.2 boundaries with fixed exported contracts, no generic expression or extra state. Numbered steps deliberately replace skill checkbox tracking because tasks.md is sole source of progress. No unresolved requirement gaps.
