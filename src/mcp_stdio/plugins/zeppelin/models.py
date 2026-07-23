"""Zeppelin input validators, status mapping, and immutable result models."""

from __future__ import annotations

import re
from enum import Enum
from typing import cast
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

_INTERPRETER_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}")

_MAX_OUTPUT_BYTES = 1_048_576
_MAX_ERROR_MESSAGE_BYTES = 4_096


class ParagraphStatus(str, Enum):
    """Normalized paragraph execution status."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class OutputKind(str, Enum):
    """Kind of a normalized paragraph output item."""

    TEXT = "TEXT"
    TABLE = "TABLE"
    HTML = "HTML"
    ANGULAR = "ANGULAR"
    IMG = "IMG"


_STATUS_MAP: dict[str, ParagraphStatus] = {
    "READY": ParagraphStatus.PENDING,
    "PENDING": ParagraphStatus.PENDING,
    "RUNNING": ParagraphStatus.RUNNING,
    "FINISHED": ParagraphStatus.FINISHED,
    "ERROR": ParagraphStatus.ERROR,
    "ABORT": ParagraphStatus.CANCELLED,
    "ABORTED": ParagraphStatus.CANCELLED,
    "CANCEL": ParagraphStatus.CANCELLED,
    "CANCELLED": ParagraphStatus.CANCELLED,
}


def normalize_paragraph_status(upstream: object) -> ParagraphStatus:
    """Map an upstream Zeppelin status to the closed normalization set."""

    if not isinstance(upstream, str):
        return ParagraphStatus.UNKNOWN
    return _STATUS_MAP.get(upstream.strip().upper(), ParagraphStatus.UNKNOWN)


def validate_notebook_name(value: object, *, max_chars: int) -> str:
    """Validate a notebook name, preserving original text."""

    if not isinstance(value, str):
        raise ValueError("notebook name must be a string")
    if not value.strip():
        raise ValueError("notebook name must not be empty")
    if len(value) > max_chars:
        raise ValueError("notebook name exceeds the configured length limit")
    return value


def validate_paragraph_title(value: object, *, max_chars: int) -> str:
    """Validate a paragraph title, preserving original text (may be empty)."""

    if not isinstance(value, str):
        raise ValueError("paragraph title must be a string")
    if len(value) > max_chars:
        raise ValueError("paragraph title exceeds the configured length limit")
    return value


def validate_paragraph_body(value: object, *, max_bytes: int) -> str:
    """Validate a paragraph body by UTF-8 byte length."""

    if not isinstance(value, str):
        raise ValueError("paragraph body must be a string")
    if not value:
        raise ValueError("paragraph body must not be empty")
    if len(value.encode("utf-8")) > max_bytes:
        raise ValueError("paragraph body exceeds the configured byte limit")
    return value


def validate_interpreter_name(value: object) -> str:
    """Validate an interpreter name against the safe syntax."""

    if not isinstance(value, str) or not _INTERPRETER_PATTERN.fullmatch(value):
        raise ValueError("interpreter name is malformed")
    return value


def validate_opaque_id(value: object, *, max_chars: int) -> str:
    """Validate an opaque ID, preserving URL syntax as data."""

    if not isinstance(value, str):
        raise ValueError("opaque id must be a string")
    if not value:
        raise ValueError("opaque id is required")
    if len(value) > max_chars:
        raise ValueError("opaque id exceeds the configured length limit")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("opaque id must not contain control characters")
    return value


def encode_opaque_id(value: object, *, max_chars: int) -> str:
    """Validate then percent-encode an opaque ID as one path segment."""

    validated = validate_opaque_id(value, max_chars=max_chars)
    return quote(validated, safe="")


def truncate_utf8(value: str, *, max_bytes: int) -> tuple[str, bool]:
    """Truncate a string to a UTF-8 byte budget without splitting characters."""

    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value, False
    return encoded[:max_bytes].decode("utf-8", errors="ignore"), True


class OutputItem(BaseModel):
    """One normalized paragraph output item."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: OutputKind
    text: str

    @field_validator("text")
    @classmethod
    def bound_text(cls, value: str) -> str:
        if len(value.encode("utf-8")) > _MAX_OUTPUT_BYTES:
            raise ValueError("output text exceeds the byte limit")
        return value


class SafeErrorDetail(BaseModel):
    """Bounded, credential-free failure detail."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message: str

    @field_validator("message")
    @classmethod
    def bound_message(cls, value: str) -> str:
        if len(value.encode("utf-8")) > _MAX_ERROR_MESSAGE_BYTES:
            raise ValueError("error message exceeds the byte limit")
        return value


class CreateNotebookResult(BaseModel):
    """Result of creating a notebook."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    notebook_id: str
    name: str


class AddParagraphResult(BaseModel):
    """Result of adding a paragraph."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    notebook_id: str
    paragraph_id: str
    title: str
    interpreter: str


class RunParagraphResult(BaseModel):
    """Result of starting paragraph execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    notebook_id: str
    paragraph_id: str
    status: ParagraphStatus


class ParagraphStatusResult(BaseModel):
    """Result of inspecting paragraph status."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    notebook_id: str
    paragraph_id: str
    status: ParagraphStatus


class ParagraphResult(BaseModel):
    """Result of retrieving paragraph outputs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    notebook_id: str
    paragraph_id: str
    status: ParagraphStatus
    outputs: tuple[OutputItem, ...] = ()
    error: SafeErrorDetail | None = None
    truncated: bool = False

    @model_validator(mode="after")
    def check_state_consistency(self) -> ParagraphResult:
        has_output = bool(self.outputs)
        has_error = self.error is not None
        if self.status == ParagraphStatus.FINISHED:
            if has_error:
                raise ValueError("finished status must not carry an error")
        elif self.status == ParagraphStatus.ERROR:
            if has_output:
                raise ValueError("error status must not carry outputs")
        else:
            raise ValueError(
                "paragraph result requires FINISHED or ERROR status"
            )
        return self


class NotebookTreeNode(BaseModel):
    """One node in the notebook directory tree."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    path: str
    notebook_id: str | None = None
    children: tuple[NotebookTreeNode, ...] = ()


class NotebookTreeResult(BaseModel):
    """Result of listing the notebook directory tree."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    nodes: tuple[NotebookTreeNode, ...] = ()


def build_notebook_tree(
    entries: tuple[tuple[str, str], ...],
) -> tuple[NotebookTreeNode, ...]:
    """Build a directory tree from flat ``(notebook_id, path)`` pairs."""

    from collections import OrderedDict

    def make_node() -> dict[str, object]:
        return {"notebook_id": None, "children": OrderedDict()}

    root: dict[str, object] = {"children": OrderedDict()}
    for notebook_id, path in entries:
        segments = [seg for seg in path.split("/") if seg]
        if not segments:
            continue
        current = root
        for i, segment in enumerate(segments):
            children = cast("OrderedDict[str, dict[str, object]]", current["children"])
            if segment not in children:
                children[segment] = make_node()
            current = children[segment]
            if i == len(segments) - 1:
                current["notebook_id"] = notebook_id

    def to_node(name: str, path: str, data: dict[str, object]) -> NotebookTreeNode:
        children_map = cast("OrderedDict[str, dict[str, object]]", data["children"])
        child_nodes: list[NotebookTreeNode] = []
        for child_name, child_data in children_map.items():
            child_path = f"{path}/{child_name}" if path else f"/{child_name}"
            child_nodes.append(to_node(child_name, child_path, child_data))
        return NotebookTreeNode(
            name=name,
            path=path,
            notebook_id=cast("str | None", data["notebook_id"]),
            children=tuple(child_nodes),
        )

    result: list[NotebookTreeNode] = []
    root_children = cast("OrderedDict[str, dict[str, object]]", root["children"])
    for name, data in root_children.items():
        result.append(to_node(name, f"/{name}", data))
    return tuple(result)
