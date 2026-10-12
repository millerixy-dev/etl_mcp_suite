"""The single Spark MCP tool translates the application service boundary."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Annotated, NoReturn

from mcp.server.fastmcp.exceptions import ToolError as FastMCPToolError
from pydantic import Field

from mcp_stdio.contracts.plugin import ToolRegistrar
from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation, unexpected_tool_error
from mcp_stdio.plugins.spark.gateway import SparkGatewayError, spark_error
from mcp_stdio.plugins.spark.models import SparkEventLogFetchResult
from mcp_stdio.plugins.spark.service import SparkEventLogService

ApplicationId = Annotated[
    str, Field(strict=True, pattern=r"^application_[0-9]+_[0-9]+$", max_length=128)
]
AttemptId = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9_-]{1,128}$")]


class SparkToolAdapter:
    def __init__(self, *, service: SparkEventLogService, secret_values: Iterable[str]) -> None:
        self._service = service
        self._secrets = tuple(value for value in secret_values if value)

    def register_tools(self, registrar: ToolRegistrar) -> None:
        registrar.add_tool(self.fetch_spark_event_log, name="fetch_spark_event_log")

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

    def _raise_error(self, error: ToolError) -> NoReturn:
        raise FastMCPToolError(
            json.dumps(
                error.to_dict(secret_values=self._secrets),
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
