"""Synthetic executor-log contracts and acquisition tests; no cluster data."""

from __future__ import annotations

import asyncio
import time

import pytest
from pydantic import ValidationError

from mcp_stdio.core.errors import ErrorCategory
from mcp_stdio.plugins.spark.executor_log_models import (
    SparkExecutorLogFetchResult,
    SparkExecutorLogRequest,
)
from mcp_stdio.plugins.spark.gateway import SparkGatewayError, spark_error


def request(**extra: object) -> SparkExecutorLogRequest:
    from mcp_stdio.plugins.spark.executor_log_models import SparkExecutorLogRequest

    return SparkExecutorLogRequest.model_validate(
        {"application_id": "application_1_42", "attempt_id": "2", "executor_id": "driver", **extra}
    )


def log_result() -> SparkExecutorLogFetchResult:
    from mcp_stdio.plugins.spark.executor_log_models import SparkExecutorLogFetchResult

    return SparkExecutorLogFetchResult(
        application_id="application_1_42",
        attempt_id="2",
        executor_id="driver",
        container_id="container_e83_1_0042_02_000001",
        log_type="stderr",
        requested_tail_bytes=65536,
        fetched_at="2026-10-14T00:00:00Z",
        coverage="complete",
        local_path="/l3/stderr.log",
        size_bytes=0,
        sha256="a" * 64,
        manifest_path="/l3/manifest.json",
    )


def test_contract_defaults_and_exact_result() -> None:
    value = request()
    assert value.log_type == "stderr" and value.tail_bytes == 65536
    assert len(log_result().model_dump()) == 12


@pytest.mark.parametrize(
    "extra",
    [
        {"application_id": "application_１_42"},
        {"attempt_id": None},
        {"attempt_id": "02"},
        {"attempt_id": "0"},
        {"executor_id": "01"},
        {"executor_id": "../1"},
        {"tail_bytes": True},
        {"tail_bytes": "1"},
        {"tail_bytes": 0},
        {"tail_bytes": 1048577},
        {"log_type": "syslog"},
        {"url": "private"},
    ],
)
def test_strict_request_rejects_unsafe_inputs(extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        request(**extra)


class FakeLogGateway:
    def __init__(self, delay: float = 0, fail: bool = False) -> None:
        self.delay, self.fail = delay, fail
        self.calls: list[tuple[SparkExecutorLogRequest, float]] = []
        self.cleaned = False

    async def fetch(
        self, request: SparkExecutorLogRequest, *, deadline: float
    ) -> SparkExecutorLogFetchResult:
        self.calls.append((request, deadline))
        try:
            await asyncio.sleep(self.delay)
            if self.fail:
                raise spark_error(ErrorCategory.NOT_FOUND)
            return log_result()
        finally:
            self.cleaned = True

    async def close(self) -> None:
        self.cleaned = True


async def test_service_validation_success_and_error_remapping() -> None:
    from mcp_stdio.plugins.spark.service import SparkExecutorLogService

    gateway = FakeLogGateway()
    service = SparkExecutorLogService(gateway=gateway, request_timeout_seconds=1)
    before = time.monotonic()
    assert await service.fetch("application_1_42", "2", "driver") == log_result()
    assert before + 1 <= gateway.calls[0][1] <= time.monotonic() + 1
    for extra in ({"tail_bytes": True}, {"unexpected": "private"}):
        with pytest.raises(SparkGatewayError) as error:
            await service.fetch("application_1_42", "2", "driver", **extra)
        assert error.value.tool_error.category == ErrorCategory.INVALID_INPUT
    assert len(gateway.calls) == 1
    gateway.fail = True
    with pytest.raises(SparkGatewayError) as error:
        await service.fetch("application_1_42", "2", "driver")
    assert error.value.tool_error.operation.value == "fetch_spark_executor_log"
    assert error.value.tool_error.identifiers == {
        "application_id": "application_1_42",
        "attempt_id": "2",
        "executor_id": "driver",
        "log_type": "stderr",
    }


async def test_service_timeout_and_cancellation_cleanup() -> None:
    from mcp_stdio.plugins.spark.service import SparkExecutorLogService

    gateway = FakeLogGateway(delay=1)
    service = SparkExecutorLogService(gateway=gateway, request_timeout_seconds=0.01)
    with pytest.raises(SparkGatewayError) as error:
        await service.fetch("application_1_42", "2", "driver")
    assert error.value.tool_error.category == ErrorCategory.TIMEOUT
    assert gateway.cleaned
    gateway.cleaned = False
    task = asyncio.create_task(
        SparkExecutorLogService(gateway=gateway, request_timeout_seconds=2).fetch(
            "application_1_42", "2", "driver"
        )
    )
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert gateway.cleaned
