"""Application service tested independently of HTTP, files and MCP."""

from __future__ import annotations

import asyncio
from typing import NoReturn

import pytest

from mcp_stdio.core.errors import ErrorCategory
from mcp_stdio.plugins.spark.gateway import SparkGatewayError, spark_error
from mcp_stdio.plugins.spark.inspection_models import InspectRequest, QueryRequest
from mcp_stdio.plugins.spark.models import SparkEventLogFetchResult, SparkEventLogFile


def result(hit: bool) -> SparkEventLogFetchResult:
    return SparkEventLogFetchResult(
        application_id="application_1_42",
        requested_attempt_id="1",
        cache_hit=hit,
        downloaded_at="2026-10-12T08:00:00Z",
        manifest_path="/l3/manifest.json",
        files=(
            SparkEventLogFile(
                attempt_id="1",
                local_path="/l3/eventlog-0001.jsonl",
                spark_version="2.4.7",
                size_bytes=10,
                sha256="a" * 64,
                source_sha256="b" * 64,
                event_count=2,
                application_end_seen=False,
            ),
        ),
    )


class FakeGateway:
    def __init__(self, hit: bool = False, delay: float = 0) -> None:
        self.hit = hit
        self.delay = delay
        self.calls: list[tuple[str, str, str | None, float]] = []

    async def lookup(
        self, application_id: str, attempt_id: str | None, *, deadline: float
    ) -> SparkEventLogFetchResult | None:
        self.calls.append(("lookup", application_id, attempt_id, deadline))
        await asyncio.sleep(self.delay)
        return result(True) if self.hit else None

    async def download(
        self, application_id: str, attempt_id: str | None, *, deadline: float
    ) -> SparkEventLogFetchResult:
        self.calls.append(("download", application_id, attempt_id, deadline))
        return result(False)

    async def close(self) -> None:
        pass


@pytest.mark.parametrize(
    ("hit", "refresh", "expected"),
    [
        (True, False, ["lookup"]),
        (False, False, ["lookup", "download"]),
        (True, True, ["download"]),
    ],
)
async def test_default_hit_miss_and_refresh(hit: bool, refresh: bool, expected: list[str]) -> None:
    from mcp_stdio.plugins.spark.service import SparkEventLogService

    gateway = FakeGateway(hit=hit)
    service = SparkEventLogService(gateway=gateway, request_timeout_seconds=2)
    value = await service.fetch("application_1_42", "1", refresh)
    assert [call[0] for call in gateway.calls] == expected
    assert value.downloaded_at == "2026-10-12T08:00:00Z"
    assert len({call[3] for call in gateway.calls}) == 1


@pytest.mark.parametrize(
    ("app", "attempt", "refresh"),
    [
        ("bad", None, False),
        ("application_1_42", "../1", False),
        ("application_1_42", "1", "true"),
    ],
)
async def test_input_rejected_before_gateway(
    app: str, attempt: str | None, refresh: object
) -> None:
    from mcp_stdio.plugins.spark.service import SparkEventLogService

    gateway = FakeGateway()
    service = SparkEventLogService(gateway=gateway, request_timeout_seconds=2)
    with pytest.raises(SparkGatewayError) as error:
        await service.fetch(app, attempt, refresh)
    assert error.value.tool_error.category == ErrorCategory.INVALID_INPUT
    assert not gateway.calls


async def test_total_deadline_includes_lookup() -> None:
    from mcp_stdio.plugins.spark.service import SparkEventLogService

    gateway = FakeGateway(delay=1)
    service = SparkEventLogService(gateway=gateway, request_timeout_seconds=0.01)
    with pytest.raises(SparkGatewayError) as error:
        await service.fetch("application_1_42")
    assert error.value.tool_error.category == ErrorCategory.TIMEOUT


async def test_domain_errors_propagate() -> None:
    from mcp_stdio.plugins.spark.service import SparkEventLogService

    class Failed(FakeGateway):
        async def download(
            self, application_id: str, attempt_id: str | None, *, deadline: float
        ) -> SparkEventLogFetchResult:
            raise spark_error(ErrorCategory.NOT_FOUND)

    service = SparkEventLogService(gateway=Failed(), request_timeout_seconds=1)
    with pytest.raises(SparkGatewayError) as error:
        await service.fetch("application_1_42", refresh=True)
    assert error.value.tool_error.category == ErrorCategory.NOT_FOUND


class FakeInspectionGateway:
    def __init__(self, delay: float = 0) -> None:
        self.calls: list[tuple[object, float]] = []
        self.delay = delay
        self.cleaned = False

    async def inspect(self, request: InspectRequest, *, deadline: float) -> NoReturn:
        self.calls.append((request, deadline))
        try:
            await asyncio.sleep(self.delay)
            raise spark_error(ErrorCategory.NOT_FOUND)
        finally:
            self.cleaned = True

    async def query(self, request: QueryRequest, *, deadline: float) -> NoReturn:
        return await self.inspect(request, deadline=deadline)

    async def close(self) -> None:
        self.cleaned = True


@pytest.mark.parametrize(
    "query, options",
    [
        (False, {}),
        (True, {}),
        (True, {"stage_attempt_id": 1}),
        (True, {"max_detail_chars": 2049}),
        (True, {"job_id": True}),
        (True, {"limit": "1"}),
    ],
)
async def test_inspection_service_validation_and_public_errors(
    query: bool, options: dict[str, object]
) -> None:
    from mcp_stdio.plugins.spark.service import SparkInspectionService

    gateway = FakeInspectionGateway()
    service = SparkInspectionService(gateway=gateway, request_timeout_seconds=1)
    with pytest.raises(SparkGatewayError) as error:
        if query:
            await service.query("/l3/manifest.json", None, "a" * 64, **options)
        else:
            await service.inspect("/l3/manifest.json", None)
    expected = ErrorCategory.INVALID_INPUT if options else ErrorCategory.NOT_FOUND
    assert error.value.tool_error.category == expected
    assert error.value.tool_error.operation.value == (
        "query_spark_events" if query else "inspect_spark_event_log"
    )
    assert bool(gateway.calls) is (not options)


async def test_inspection_service_timeout_awaits_cleanup() -> None:
    from mcp_stdio.plugins.spark.service import SparkInspectionService

    gateway = FakeInspectionGateway(delay=1)
    service = SparkInspectionService(gateway=gateway, request_timeout_seconds=0.01)
    with pytest.raises(SparkGatewayError) as error:
        await service.inspect("/l3/manifest.json", None)
    assert error.value.tool_error.category == ErrorCategory.TIMEOUT
    assert error.value.tool_error.operation.value == "inspect_spark_event_log"
    assert gateway.cleaned


async def test_inspection_service_cancellation_awaits_cleanup() -> None:
    from mcp_stdio.plugins.spark.service import SparkInspectionService

    gateway = FakeInspectionGateway(delay=1)
    task = asyncio.create_task(
        SparkInspectionService(gateway=gateway, request_timeout_seconds=2).inspect(
            "/l3/manifest.json", None
        )
    )
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert gateway.cleaned
