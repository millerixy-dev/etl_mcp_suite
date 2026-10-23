"""Spark service port and safe adapter errors."""

from __future__ import annotations

from typing import Protocol

from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation, safe_error_identifiers
from mcp_stdio.plugins.spark.executor_log_models import (
    SparkExecutorLogFetchResult,
    SparkExecutorLogRequest,
)
from mcp_stdio.plugins.spark.inspection_models import (
    InspectRequest,
    QueryRequest,
    SparkEventLogInspectionResult,
    SparkEventQueryResult,
)
from mcp_stdio.plugins.spark.metrics_models import (
    SparkStageMetricsResult,
    SparkTaskDistributionResult,
    StageMetricsRequest,
    TaskDistributionRequest,
)
from mcp_stdio.plugins.spark.models import SparkEventLogFetchResult


class SparkGatewayError(RuntimeError):
    def __init__(self, tool_error: ToolError) -> None:
        self.tool_error = tool_error
        super().__init__(tool_error.message)


def spark_error(
    category: ErrorCategory,
    *,
    application_id: str | None = None,
    attempt_id: str | None = None,
    retryable: bool = False,
    explanation: str | None = None,
) -> SparkGatewayError:
    operation = ToolOperation.FETCH_SPARK_EVENT_LOG
    return SparkGatewayError(
        ToolError.create(
            category=category,
            operation=operation,
            retryable=retryable,
            identifiers=safe_error_identifiers(
                operation,
                {
                    "application_id": application_id,
                    "attempt_id": attempt_id,
                },
            ),
            explanation=explanation,
        )
    )


class SparkEventLogGateway(Protocol):
    async def lookup(
        self, application_id: str, attempt_id: str | None, *, deadline: float
    ) -> SparkEventLogFetchResult | None: ...
    async def download(
        self, application_id: str, attempt_id: str | None, *, deadline: float
    ) -> SparkEventLogFetchResult: ...
    async def close(self) -> None: ...


class SparkInspectionGateway(Protocol):
    async def inspect(
        self, request: InspectRequest, *, deadline: float
    ) -> SparkEventLogInspectionResult: ...
    async def query(self, request: QueryRequest, *, deadline: float) -> SparkEventQueryResult: ...
    async def close(self) -> None: ...


class SparkMetricsGateway(Protocol):
    async def stage_metrics(
        self, request: StageMetricsRequest, *, deadline: float
    ) -> SparkStageMetricsResult: ...
    async def task_distribution(
        self, request: TaskDistributionRequest, *, deadline: float
    ) -> SparkTaskDistributionResult: ...
    async def close(self) -> None: ...


class SparkExecutorLogGateway(Protocol):
    async def fetch(
        self, request: SparkExecutorLogRequest, *, deadline: float
    ) -> SparkExecutorLogFetchResult: ...
    async def close(self) -> None: ...
