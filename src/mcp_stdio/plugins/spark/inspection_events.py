"""Stateless extraction of direct scalar identifiers from one Spark event."""

from __future__ import annotations

import json
import re
from typing import cast

from mcp_stdio.plugins.spark.files import redact_event
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


def task_reason(event: dict[str, object]) -> tuple[str, bool]:
    """Return the observed reason and whether it is explicitly valid."""
    value = _object(event.get("Task End Reason")).get("Reason")
    valid = (
        isinstance(value, str)
        and 1 <= len(value) <= 128
        and not any(ord(c) < 32 or ord(c) == 127 for c in value)
    )
    return (cast(str, value), True) if valid else ("UNKNOWN", False)


def event_details(
    event: dict[str, object], secrets: tuple[str, ...], max_chars: int = 2048
) -> tuple[str, bool]:
    """Fixed diagnostic projection with one whole-text bound and repeat redaction."""
    name = event.get("Event")
    fields: tuple[str, ...]
    source = event
    if name == "SparkListenerJobStart":
        fields = ("Submission Time", "Stage IDs", "Properties")
        source = dict(event)
        properties = _object(event.get("Properties"))
        if "spark.sql.execution.id" in properties:
            source["Properties"] = {"spark.sql.execution.id": properties["spark.sql.execution.id"]}
        else:
            source.pop("Properties", None)
    elif name == "SparkListenerJobEnd":
        fields = ("Completion Time", "Job Result")
    elif name in ("SparkListenerStageSubmitted", "SparkListenerStageCompleted"):
        fields = (
            "Stage Name",
            "Parent IDs",
            "Submission Time",
            "Completion Time",
            "Failure Reason",
        )
        source = _object(event.get("Stage Info"))
    elif name in ("SparkListenerTaskStart", "SparkListenerTaskEnd"):
        fields = ("Task End Reason", "Task Info", "Task Metrics")
    elif name in ("SparkListenerExecutorAdded", "SparkListenerExecutorRemoved"):
        fields = ("Timestamp", "Executor Info", "Removed Reason")
        source = dict(event)
        if "Executor Info" in source:
            info = _object(source["Executor Info"])
            source["Executor Info"] = {
                key: info[key] for key in ("Host", "Total Cores") if key in info
            }
    elif name in (
        "SparkListenerApplicationStart",
        "SparkListenerApplicationEnd",
        "SparkListenerLogStart",
    ):
        fields = ("Timestamp", "App Name", "App ID", "App Attempt ID", "Spark Version")
    elif name in (
        "org.apache.spark.sql.execution.ui.SparkListenerSQLExecutionStart",
        "org.apache.spark.sql.execution.ui.SparkListenerSQLExecutionEnd",
    ):
        fields = ("executionId", "time", "description", "details", "physicalPlanDescription")
    elif name == "SparkListenerEnvironmentUpdate":
        fields = ("Spark Properties",)
        source = _object(redact_event(event, secrets))
    else:
        fields = ()
    projected = {key: source[key] for key in fields if key in source} if fields else event
    safe = _object(redact_event(projected, secrets))
    text = (
        "\n".join(
            f"{key}: {json.dumps(safe[key], ensure_ascii=False, sort_keys=True)}"
            for key in fields
            if key in safe
        )
        if fields
        else json.dumps(safe, ensure_ascii=False, sort_keys=True)
    )
    truncated = len(text) > max_chars
    if truncated:
        head = max_chars // 2
        text = text[:head] + text[-(max_chars - head) :]
    # A head/tail join can reconstruct a secret absent from the original text.
    safe_text = _object(redact_event({"details": text}, secrets))["details"]
    text = cast(str, safe_text)
    # Redaction markers may expand very short limits. Prefix clipping cannot
    # reconstruct a new join, and keeps the single promised text bound.
    return text[:max_chars], truncated
