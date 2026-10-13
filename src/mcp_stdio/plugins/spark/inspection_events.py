"""Stateless extraction of direct scalar identifiers from one Spark event."""

from __future__ import annotations

import re
from typing import cast

from mcp_stdio.plugins.spark.inspection_models import SparkEventIds


def _object(value: object) -> dict[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _integer(value: object) -> int | None:
    return value if type(value) is int and 0 <= value <= 2**63 - 1 else None


def _executor(value: object) -> str | None:
    return (
        value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) else None
    )


def direct_ids(event: dict[str, object]) -> SparkEventIds:
    stage = _object(event.get("Stage Info"))
    task = _object(event.get("Task Info"))
    block = _object(event.get("Block Manager ID"))
    execution = _integer(event.get("executionId"))
    if execution is None and event.get("Event") == "SparkListenerJobStart":
        value = _object(event.get("Properties")).get("spark.sql.execution.id")
        if isinstance(value, str) and re.fullmatch(r"[0-9]{1,19}", value):
            execution = _integer(int(value))
    return SparkEventIds(
        execution_id=execution,
        job_id=_integer(event.get("Job ID")),
        stage_id=_integer(event.get("Stage ID"))
        if "Stage ID" in event
        else _integer(stage.get("Stage ID")),
        stage_attempt_id=_integer(event.get("Stage Attempt ID"))
        if "Stage Attempt ID" in event
        else _integer(stage.get("Stage Attempt ID")),
        task_id=_integer(task.get("Task ID")),
        executor_id=_executor(event.get("Executor ID"))
        if "Executor ID" in event
        else _executor(task.get("Executor ID"))
        if "Executor ID" in task
        else _executor(block.get("Executor ID")),
    )
