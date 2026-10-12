"""Validated Spark use case independent of MCP and external adapters."""

from __future__ import annotations

import asyncio
import time

from pydantic import ValidationError

from mcp_stdio.core.errors import ErrorCategory
from mcp_stdio.plugins.spark.gateway import SparkEventLogGateway, spark_error
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
