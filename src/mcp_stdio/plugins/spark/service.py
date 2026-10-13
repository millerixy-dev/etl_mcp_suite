"""Validated Spark use case independent of MCP and external adapters."""

from __future__ import annotations

import asyncio
import time

from pydantic import ValidationError

from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation, safe_error_identifiers
from mcp_stdio.plugins.spark.gateway import (
    SparkEventLogGateway,
    SparkGatewayError,
    SparkInspectionGateway,
    SparkMetricsGateway,
    spark_error,
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
from mcp_stdio.plugins.spark.models import FetchRequest, SparkEventLogFetchResult


class SparkEventLogService:
    def __init__(self, *, gateway: SparkEventLogGateway, request_timeout_seconds: float) -> None:
        self._gateway = gateway
        self._timeout = request_timeout_seconds

    async def fetch(
        self, application_id: object, attempt_id: object = None, refresh: object = False
    ) -> SparkEventLogFetchResult:
        try:
            request = FetchRequest.model_validate(
                {
                    "application_id": application_id,
                    "attempt_id": attempt_id,
                    "refresh": refresh,
                }
            )
        except ValidationError:
            raise spark_error(ErrorCategory.INVALID_INPUT) from None
        deadline = time.monotonic() + self._timeout
        try:
            return await asyncio.wait_for(self._fetch(request, deadline), timeout=self._timeout)
        except asyncio.TimeoutError:
            raise spark_error(
                ErrorCategory.TIMEOUT,
                application_id=request.application_id,
                attempt_id=request.attempt_id,
                retryable=True,
            ) from None

    async def _fetch(self, request: FetchRequest, deadline: float) -> SparkEventLogFetchResult:
        if not request.refresh:
            hit = await self._gateway.lookup(
                request.application_id, request.attempt_id, deadline=deadline
            )
            if hit is not None:
                return hit
        return await self._gateway.download(
            request.application_id, request.attempt_id, deadline=deadline
        )


class SparkInspectionService:
    """Validate local evidence requests without depending on file or MCP adapters."""

    def __init__(self, *, gateway: SparkInspectionGateway, request_timeout_seconds: float) -> None:
        self._gateway = gateway
        self._timeout = request_timeout_seconds

    async def inspect(
        self, manifest_path: object, attempt_id: object
    ) -> SparkEventLogInspectionResult:
        operation = ToolOperation.INSPECT_SPARK_EVENT_LOG
        try:
            request = InspectRequest.model_validate(
                {"manifest_path": manifest_path, "attempt_id": attempt_id}
            )
        except ValidationError:
            raise _error(ErrorCategory.INVALID_INPUT, operation) from None
        deadline = time.monotonic() + self._timeout
        try:
            return await asyncio.wait_for(
                self._gateway.inspect(request, deadline=deadline),
                timeout=max(0, deadline - time.monotonic()),
            )
        except asyncio.TimeoutError:
            raise _error(ErrorCategory.TIMEOUT, operation, retryable=True) from None
        except SparkGatewayError as error:
            raise _remap(error, operation) from None

    async def query(
        self,
        manifest_path: object,
        attempt_id: object,
        expected_sha256: object,
        **selection: object,
    ) -> SparkEventQueryResult:
        operation = ToolOperation.QUERY_SPARK_EVENTS
        try:
            request = QueryRequest.model_validate(
                {
                    "manifest_path": manifest_path,
                    "attempt_id": attempt_id,
                    "expected_sha256": expected_sha256,
                    **selection,
                }
            )
        except ValidationError:
            raise _error(ErrorCategory.INVALID_INPUT, operation) from None
        deadline = time.monotonic() + self._timeout
        try:
            return await asyncio.wait_for(
                self._gateway.query(request, deadline=deadline),
                timeout=max(0, deadline - time.monotonic()),
            )
        except asyncio.TimeoutError:
            raise _error(ErrorCategory.TIMEOUT, operation, retryable=True) from None
        except SparkGatewayError as error:
            raise _remap(error, operation) from None


def _error(
    category: ErrorCategory, operation: ToolOperation, *, retryable: bool = False
) -> SparkGatewayError:
    return SparkGatewayError(
        ToolError.create(category=category, operation=operation, retryable=retryable)
    )


def _remap(error: SparkGatewayError, operation: ToolOperation) -> SparkGatewayError:
    value = error.tool_error
    return SparkGatewayError(
        ToolError.create(
            category=value.category,
            operation=operation,
            retryable=value.retryable,
            identifiers=safe_error_identifiers(operation, value.identifiers),
        )
    )


class SparkMetricsService:
    """Validate fixed-snapshot metrics through the read-only domain port."""

    def __init__(self, *, gateway: SparkMetricsGateway, request_timeout_seconds: float) -> None:
        self._gateway = gateway
        self._timeout = request_timeout_seconds

    async def stage_metrics(
        self,
        manifest_path: object,
        attempt_id: object,
        expected_sha256: object,
        **selection: object,
    ) -> SparkStageMetricsResult:
        operation = ToolOperation.GET_SPARK_STAGE_METRICS
        try:
            request = StageMetricsRequest.model_validate(
                {
                    "manifest_path": manifest_path,
                    "attempt_id": attempt_id,
                    "expected_sha256": expected_sha256,
                    **selection,
                }
            )
        except ValidationError:
            raise _error(ErrorCategory.INVALID_INPUT, operation) from None
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

    async def task_distribution(
        self,
        manifest_path: object,
        attempt_id: object,
        expected_sha256: object,
        **selection: object,
    ) -> SparkTaskDistributionResult:
        operation = ToolOperation.GET_SPARK_TASK_DISTRIBUTION
        try:
            request = TaskDistributionRequest.model_validate(
                {
                    "manifest_path": manifest_path,
                    "attempt_id": attempt_id,
                    "expected_sha256": expected_sha256,
                    **selection,
                }
            )
        except ValidationError:
            raise _error(ErrorCategory.INVALID_INPUT, operation) from None
        deadline = time.monotonic() + self._timeout
        try:
            return await asyncio.wait_for(
                self._gateway.task_distribution(request, deadline=deadline),
                timeout=max(0, deadline - time.monotonic()),
            )
        except asyncio.TimeoutError:
            raise _error(ErrorCategory.TIMEOUT, operation, retryable=True) from None
        except SparkGatewayError as error:
            raise _remap(error, operation) from None
