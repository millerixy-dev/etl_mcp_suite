"""Spark MCP tools translate the application service boundary."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Iterable
from typing import Annotated, NoReturn

from mcp.server.fastmcp.exceptions import ToolError as FastMCPToolError
from pydantic import Field, ValidationError

from mcp_stdio.contracts.plugin import ToolRegistrar
from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation, unexpected_tool_error
from mcp_stdio.plugins.spark.files import redact_event
from mcp_stdio.plugins.spark.gateway import SparkGatewayError, spark_error
from mcp_stdio.plugins.spark.inspection_models import (
    SparkEventLogInspectionResult,
    SparkEventQueryResult,
)
from mcp_stdio.plugins.spark.models import SparkEventLogFetchResult
from mcp_stdio.plugins.spark.service import SparkEventLogService, SparkInspectionService

ApplicationId = Annotated[
    str, Field(strict=True, pattern=r"^application_[0-9]+_[0-9]+$", max_length=128)
]
AttemptId = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9_-]{1,128}$")]

ManifestPath = Annotated[str, Field(strict=True, min_length=1, max_length=4096)]
Sha256 = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
SparkId = Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)]
PhysicalLine = Annotated[int, Field(strict=True, ge=1, le=2**63 - 1)]
EventType = Annotated[str, Field(strict=True, min_length=1, max_length=512)]
TaskReason = Annotated[str, Field(strict=True, min_length=1, max_length=128)]
EventTypes = Annotated[list[EventType], Field(strict=True, min_length=1, max_length=16)]
Lines = Annotated[list[PhysicalLine], Field(strict=True, min_length=1, max_length=20)]
Limit = Annotated[int, Field(strict=True, ge=1, le=20)]
DetailChars = Annotated[int, Field(strict=True, ge=1, le=32768)]


class SparkToolAdapter:
    def __init__(
        self,
        *,
        service: SparkEventLogService,
        secret_values: Iterable[str],
        inspection_service: SparkInspectionService | None = None,
    ) -> None:
        self._service = service
        self._inspection_service = inspection_service
        self._secrets = tuple(value for value in secret_values if value)

    def register_tools(self, registrar: ToolRegistrar) -> None:
        registrar.add_tool(self.fetch_spark_event_log, name="fetch_spark_event_log")
        registrar.add_tool(self.inspect_spark_event_log, name="inspect_spark_event_log")
        registrar.add_tool(self.query_spark_events, name="query_spark_events")

    async def fetch_spark_event_log(
        self,
        application_id: ApplicationId,
        attempt_id: AttemptId | None = None,
        refresh: Annotated[bool, Field(strict=True)] = False,
    ) -> SparkEventLogFetchResult:
        """Download validated, redacted Spark JSONL to local L3; refresh bypasses reuse."""
        try:
            result = await self._service.fetch(application_id, attempt_id, refresh)
            if any(secret in result.model_dump_json() for secret in self._secrets):
                raise spark_error(ErrorCategory.UNEXPECTED_RESPONSE)
            return result
        except SparkGatewayError as error:
            self._raise_error(error.tool_error)
        except Exception as error:
            self._raise_error(
                unexpected_tool_error(error, operation=ToolOperation.FETCH_SPARK_EVENT_LOG)
            )

    async def inspect_spark_event_log(
        self,
        manifest_path: ManifestPath,
        attempt_id: AttemptId | None,
    ) -> SparkEventLogInspectionResult:
        """Inspect one verified local snapshot; nullable attempt must be supplied explicitly."""
        operation = ToolOperation.INSPECT_SPARK_EVENT_LOG
        if self._inspection_service is None:
            self._raise_error(
                ToolError.create(
                    category=ErrorCategory.UNEXPECTED_RESPONSE, operation=operation, retryable=False
                )
            )
        result = await self._inspection_result(
            self._inspection_service.inspect(manifest_path, attempt_id), operation
        )
        assert isinstance(result, SparkEventLogInspectionResult)
        return result

    async def query_spark_events(
        self,
        manifest_path: ManifestPath,
        attempt_id: AttemptId | None,
        expected_sha256: Sha256,
        event_types: EventTypes | None = None,
        execution_id: SparkId | None = None,
        job_id: SparkId | None = None,
        stage_id: SparkId | None = None,
        stage_attempt_id: SparkId | None = None,
        task_id: SparkId | None = None,
        executor_id: AttemptId | None = None,
        task_end_reason: TaskReason | None = None,
        lines: Lines | None = None,
        after_line: SparkId = 0,
        limit: Limit = 20,
        max_detail_chars: DetailChars = 2048,
    ) -> SparkEventQueryResult:
        """Query only direct event fields in a fixed digest; reread refs with lines."""
        operation = ToolOperation.QUERY_SPARK_EVENTS
        if self._inspection_service is None:
            self._raise_error(
                ToolError.create(
                    category=ErrorCategory.UNEXPECTED_RESPONSE, operation=operation, retryable=False
                )
            )
        result = await self._inspection_result(
            self._inspection_service.query(
                manifest_path,
                attempt_id,
                expected_sha256,
                event_types=event_types,
                execution_id=execution_id,
                job_id=job_id,
                stage_id=stage_id,
                stage_attempt_id=stage_attempt_id,
                task_id=task_id,
                executor_id=executor_id,
                task_end_reason=task_end_reason,
                lines=lines,
                after_line=after_line,
                limit=limit,
                max_detail_chars=max_detail_chars,
            ),
            operation,
        )
        assert isinstance(result, SparkEventQueryResult)
        return result

    async def _inspection_result(
        self,
        call: Awaitable[SparkEventLogInspectionResult | SparkEventQueryResult],
        operation: ToolOperation,
    ) -> SparkEventLogInspectionResult | SparkEventQueryResult:
        try:
            result = await call
            # Metadata can carry vendor labels too; redact only the public copy.
            redacted = redact_event(result.model_dump(mode="json"), self._secrets)
            public = type(result).model_validate_json(json.dumps(redacted, ensure_ascii=False))
            if any(secret in public.model_dump_json() for secret in self._secrets):
                raise SparkGatewayError(
                    ToolError.create(
                        category=ErrorCategory.UNEXPECTED_RESPONSE,
                        operation=operation,
                        retryable=False,
                    )
                )
            return public
        except ValidationError:
            self._raise_error(
                ToolError.create(
                    category=ErrorCategory.UNEXPECTED_RESPONSE, operation=operation, retryable=False
                )
            )
        except SparkGatewayError as error:
            self._raise_error(error.tool_error)
        except Exception as error:
            self._raise_error(unexpected_tool_error(error, operation=operation))

    def _raise_error(self, error: ToolError) -> NoReturn:
        raise FastMCPToolError(
            json.dumps(
                error.to_dict(secret_values=self._secrets),
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
