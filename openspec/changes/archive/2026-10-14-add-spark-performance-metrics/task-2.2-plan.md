# Task 2.2 implementation plan

**Goal:** Exact full-snapshot selected Stage-attempt distributions and bounded Task ranking.
**Architecture:** Reuse VerifiedEventLogReader and existing adapter lifecycle. Six array("Q") buffers permit 2**64-2 Shuffle sums; a min-heap holds at most limit projections.
**Tech Stack:** Python >=3.10, standard library, existing Pydantic DTOs, uv pytest.
**Authority:** Active design sections 1,2,4,5 and spark-performance-metrics spec; tasks.md remains sole checkbox source.

## RED
Append the following tests to tests/unit/plugins/spark/test_metrics.py:
```python

def distribution_request(request: InspectRequest, **filters: object):
    from mcp_stdio.plugins.spark.metrics_models import TaskDistributionRequest
    return TaskDistributionRequest.model_validate({
        **stage_request(request).model_dump(), "stage_id": 17, "stage_attempt_id": 0, **filters,
    })


def complete_task(value: int, *, reason: object = "Success") -> dict[str, object]:
    return {**measured_task(17, 0, reason, value), "Task Info": {
        "Launch Time": 1, "Finish Time": value + 1, "Task ID": value, "Executor ID": "2",
        "Index": 0, "Speculative": True,
    }, "Task Metrics": {
        "Executor Run Time": value, "JVM GC Time": value,
        "Input Metrics": {"Bytes Read": value}, "Shuffle Read Metrics": {
            "Remote Bytes Read": value, "Local Bytes Read": 0, "Fetch Wait Time": value,
        },
    }}


@pytest.mark.asyncio
@pytest.mark.parametrize("order_by", ["duration_ms", "executor_run_time_ms", "jvm_gc_time_ms",
                                       "input_bytes", "shuffle_read_bytes", "shuffle_fetch_wait_ms"])
async def test_distribution_full_samples_ties_and_refs(tmp_path: Path, order_by: str) -> None:
    adapter, request = snapshot(tmp_path, [
        complete_task(3), complete_task(3), complete_task(1), complete_task(0),
        complete_task(900), complete_task(999, reason="FetchFailed"),
        complete_task(999, reason=None), measured_task(18, 0, value=999),
        {**complete_task(999), "Stage ID": True},
        {**complete_task(999), "Stage ID": None, "Stage Info": {
            "Stage ID": 17, "Stage Attempt ID": 0,
        }},
    ])
    result = await adapter.task_distribution(distribution_request(request, order_by=order_by, limit=2),
                                              deadline=time.monotonic() + 10)
    assert (result.task_end_count, result.successful_task_end_count,
            result.non_success_task_end_count, result.unknown_reason_task_end_count) == (7, 5, 1, 1)
    assert result.ranked_task_count == 5 and result.tasks_omitted == 3
    assert [row.ref.line for row in result.top_tasks] == [7, 3]
    for distribution in result.distributions.model_dump().values():
        assert distribution == {"valid_count": 5, "missing_count": 0,
                                "min": 0, "p50": 3, "p95": 900, "max": 900}
    reread = await adapter.query(query_request(request, lines=[7]), deadline=time.monotonic() + 10)
    assert reread.events[0].ref == result.top_tasks[0].ref
    assert reread.events[0].ids.task_id == result.top_tasks[0].task_id == 900
    unlimited = await adapter.task_distribution(distribution_request(request, order_by=order_by),
                                                 deadline=time.monotonic() + 10)
    assert unlimited.distributions == result.distributions
    assert [row.ref.line for row in unlimited.top_tasks] == [7, 3, 4, 5, 6]
    await adapter.close()


@pytest.mark.asyncio
async def test_distribution_independent_missing_unknown_ids_and_large_shuffle(tmp_path: Path) -> None:
    large = complete_task(1)
    large["Task Info"] = {"Launch Time": 0, "Finish Time": 1,
                          "Task ID": True, "Executor ID": "invalid id"}
    large["Task Metrics"] = {"Shuffle Read Metrics": {
        "Remote Bytes Read": 2**63 - 1, "Local Bytes Read": 2**63 - 1,
    }}
    partial = measured_task(17, 0, value=0)
    partial["Task Info"] = {"Launch Time": 1, "Finish Time": 1}
    adapter, request = snapshot(tmp_path, [large, partial, complete_task(2)])
    result = await adapter.task_distribution(
        distribution_request(request, order_by="shuffle_read_bytes", limit=1),
        deadline=time.monotonic() + 10)
    assert result.top_tasks[0].shuffle_read_bytes == 2**64 - 2
    assert result.top_tasks[0].task_id is None and result.top_tasks[0].executor_id is None
    assert result.distributions.shuffle_read_bytes.valid_count == 3
    assert result.distributions.executor_run_time_ms.missing_count == 2
    assert result.distributions.input_bytes.missing_count == 1
    by_gc = await adapter.task_distribution(distribution_request(request, order_by="jvm_gc_time_ms"),
                                             deadline=time.monotonic() + 10)
    assert by_gc.ranked_task_count == 1 and by_gc.tasks_omitted == 0
    assert by_gc.distributions == result.distributions
    await adapter.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("records", [[], [complete_task(2, reason="FetchFailed")]])
async def test_distribution_empty_success_population(tmp_path: Path, records: list[dict[str, object]]) -> None:
    adapter, request = snapshot(tmp_path, records)
    result = await adapter.task_distribution(distribution_request(request),
                                              deadline=time.monotonic() + 10)
    assert result.task_end_count == len(records)
    assert result.top_tasks == () and result.ranked_task_count == result.tasks_omitted == 0
    assert all(value == {"valid_count": 0, "missing_count": 0, "min": None,
                         "p50": None, "p95": None, "max": None}
               for value in result.distributions.model_dump().values())
    await adapter.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["expected_hash", "digest", "tail"])
async def test_distribution_validates_full_tail_before_publication(tmp_path: Path, corruption: str) -> None:
    adapter, request = snapshot(tmp_path, [complete_task(900), complete_task(1)])
    metrics_request = distribution_request(request, limit=1)
    manifest = Path(request.manifest_path)
    body = json.loads(manifest.read_text())
    path = Path(body["files"][0]["local_path"])
    if corruption == "expected_hash":
        metrics_request = metrics_request.model_copy(update={"expected_sha256": "0" * 64})
    elif corruption == "digest":
        path.write_bytes(path.read_bytes().replace(b'"Finish Time":2', b'"Finish Time":3'))
    else:
        raw = path.read_bytes() + b'{broken\n'
        path.write_bytes(raw)
        body["files"][0].update(size_bytes=len(raw), event_count=6,
                                sha256=hashlib.sha256(raw).hexdigest())
        manifest.write_text(json.dumps(body))
        metrics_request = distribution_request(request, limit=1)
    with pytest.raises(SparkGatewayError):
        await adapter.task_distribution(metrics_request, deadline=time.monotonic() + 10)
    await adapter.close()


@pytest.mark.asyncio
async def test_distribution_cancel_timeout_and_close(tmp_path: Path) -> None:
    adapter, request = snapshot(tmp_path, [complete_task(1) for _ in range(1000)])
    metrics_request = distribution_request(request)
    with pytest.raises(SparkGatewayError):
        await adapter.task_distribution(metrics_request, deadline=time.monotonic() - 1)
    worker = asyncio.create_task(adapter.task_distribution(metrics_request,
                                                           deadline=time.monotonic() + 10))
    await asyncio.sleep(0)
    worker.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker
    worker = asyncio.create_task(adapter.task_distribution(metrics_request,
                                                           deadline=time.monotonic() + 10))
    await asyncio.sleep(0)
    await adapter.close()
    assert worker.cancelled()
    assert not adapter._active
    with pytest.raises(asyncio.CancelledError):
        await adapter.task_distribution(metrics_request, deadline=time.monotonic() + 10)

```
Run `UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/plugins/spark/test_metrics.py -k distribution`.
Expected missing adapter.task_distribution failures.

## GREEN
Append to src/mcp_stdio/plugins/spark/metrics.py after adding imports for array, heapq, direct_ids, SparkEventIds, METRIC_NAMES, metric_distribution and named Task DTOs:
```python


async def scan_task_distribution(
    reader: VerifiedEventLogReader, request: TaskDistributionRequest, *, deadline: float
) -> SparkTaskDistributionResult:
    samples = {name: array("Q") for name in METRIC_NAMES}
    candidates: list[tuple[int, int, TaskMetricValues, SparkEventIds]] = []
    successful = non_success = unknown = ranked = 0

    def visit(line: int, event: dict[str, object]) -> None:
        nonlocal successful, non_success, unknown, ranked
        if event["Event"] != "SparkListenerTaskEnd" or (
            metric_integer(event.get("Stage ID")), metric_integer(event.get("Stage Attempt ID"))
        ) != (request.stage_id, request.stage_attempt_id):
            return
        outcome = task_outcome(event)
        if outcome == "non_success":
            non_success += 1
            return
        if outcome == "unknown":
            unknown += 1
            return
        successful += 1
        values = task_metric_values(event)
        for name in METRIC_NAMES:
            value = getattr(values, name)
            if value is not None:
                samples[name].append(value)
        score = getattr(values, request.order_by)
        if score is not None:
            ranked += 1
            key = (score, -line)
            if len(candidates) < request.limit:
                heapq.heappush(candidates, (*key, values, direct_ids(event)))
            elif key > candidates[0][:2]:
                heapq.heapreplace(candidates, (*key, values, direct_ids(event)))

    scan = await reader.read(request, visit, deadline=deadline)
    await checkpoint(deadline)
    distributions = {}
    for name in METRIC_NAMES:
        await checkpoint(deadline)
        distributions[name] = metric_distribution(samples[name], successful)
        await checkpoint(deadline)
    await checkpoint(deadline)
    ordered = sorted(candidates, key=lambda item: (-item[0], -item[1]))
    await checkpoint(deadline)
    top_tasks = []
    for _, negative_line, values, ids in ordered:
        await checkpoint(deadline)
        top_tasks.append(SparkRankedTask(
            **values.model_dump(), task_id=ids.task_id, executor_id=ids.executor_id,
            ref=SparkEventRef(sha256=scan.snapshot.sha256, line=-negative_line),
        ))
    await checkpoint(deadline)
    return SparkTaskDistributionResult(
        snapshot=scan.snapshot, coverage=scan.coverage,
        stage_id=request.stage_id, stage_attempt_id=request.stage_attempt_id,
        task_end_count=successful + non_success + unknown,
        successful_task_end_count=successful, non_success_task_end_count=non_success,
        unknown_reason_task_end_count=unknown,
        distributions=TaskMetricDistributions.model_validate(distributions),
        order_by=request.order_by, ranked_task_count=ranked,
        top_tasks=tuple(top_tasks), tasks_omitted=ranked - len(top_tasks),
    )

```
Extend the adapter's existing _active union by asyncio.Task[SparkTaskDistributionResult], import the request/result and scan_task_distribution, and insert:
```python
    async def task_distribution(
        self, request: TaskDistributionRequest, *, deadline: float
    ) -> SparkTaskDistributionResult:
        if self._closed:
            raise asyncio.CancelledError
        worker = asyncio.create_task(scan_task_distribution(self._reader, request, deadline=deadline))
        self._active.add(worker)
        try:
            return await worker
        finally:
            self._active.discard(worker)
```
Run sequentially:
`UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/plugins/spark/test_metrics.py tests/unit/plugins/spark/test_cache.py tests/unit/plugins/spark/test_inspection.py`
`UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio ruff check src/mcp_stdio/plugins/spark/metrics.py src/mcp_stdio/plugins/spark/inspection.py tests/unit/plugins/spark/test_metrics.py`
`UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pyright`

## Refactor and self-review
Reuse existing metric extraction/statistic and ID validation; verify deadline before/after each synchronous statistics/ranking operation. Heap keys are unique physical lines, so Pydantic projections never participate in comparison. All successful samples contribute before limit; unknown IDs remain null. Memory O(six selected-group numeric samples + limit fixed projections), no raw event retention. Compact buffers support unsigned sums; sorting temporarily allocates one metric's Python integers. No persistent state/network/config/dependencies. Add post-scan deadline/cancellation verification before publication if needed. Record evidence in task-2.2-report.md; controlling agent gates tasks.md.

## Publication checkpoint refinement
Evidence test adds a synchronous-result-validation deadline expiry; result-validation returned without a postvalidation checkpoint. Hypothesis and minimal fix: assign result, await checkpoint(deadline), then return result. Existing statistics/top-projection checkpoints must stay intact.
```python
    result = SparkTaskDistributionResult(
        snapshot=scan.snapshot,
        coverage=scan.coverage,
        stage_id=request.stage_id,
        stage_attempt_id=request.stage_attempt_id,
        task_end_count=successful + non_success + unknown,
        successful_task_end_count=successful,
        non_success_task_end_count=non_success,
        unknown_reason_task_end_count=unknown,
        distributions=TaskMetricDistributions.model_validate(distributions),
        order_by=request.order_by,
        ranked_task_count=ranked,
        top_tasks=tuple(top_tasks),
        tasks_omitted=ranked - len(top_tasks),
    )
    await checkpoint(deadline)
    return result
```
Exact refinement test: `UV_NO_EDITABLE=1 uv run --locked --reinstall-package hive-cli-mcp-stdio pytest tests/unit/plugins/spark/test_metrics.py -k original_deadline_after_computation`.
