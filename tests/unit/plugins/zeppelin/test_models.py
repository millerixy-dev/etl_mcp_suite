"""Zeppelin input and result model contract tests."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import ValidationError

from mcp_stdio.plugins.zeppelin.models import (
    AddParagraphResult,
    CreateNotebookResult,
    OutputItem,
    OutputKind,
    ParagraphResult,
    ParagraphStatus,
    ParagraphStatusResult,
    RunParagraphResult,
    SafeErrorDetail,
    encode_opaque_id,
    normalize_paragraph_status,
    truncate_utf8,
    validate_interpreter_name,
    validate_notebook_name,
    validate_opaque_id,
    validate_paragraph_body,
    validate_paragraph_title,
)


def test_input_validators_preserve_valid_original_text() -> None:
    assert validate_notebook_name("  notebook  ", max_chars=32) == "  notebook  "
    assert validate_paragraph_title("  title  ", max_chars=32) == "  title  "
    assert validate_paragraph_title("", max_chars=32) == ""
    assert validate_paragraph_body("  body  ", max_bytes=32) == "  body  "
    assert validate_interpreter_name("spark.sql") == "spark.sql"


@pytest.mark.parametrize(
    "invoke",
    [
        lambda: validate_notebook_name("", max_chars=8),
        lambda: validate_notebook_name("   ", max_chars=8),
        lambda: validate_notebook_name("123456789", max_chars=8),
        lambda: validate_notebook_name(123, max_chars=8),  # type: ignore[arg-type]
        lambda: validate_paragraph_title("123456789", max_chars=8),
        lambda: validate_paragraph_title(None, max_chars=8),  # type: ignore[arg-type]
        lambda: validate_paragraph_body("", max_bytes=8),
        lambda: validate_paragraph_body("你好", max_bytes=5),
        lambda: validate_paragraph_body(123, max_bytes=8),  # type: ignore[arg-type]
        lambda: validate_interpreter_name("spark sql"),
        lambda: validate_interpreter_name("1spark"),
    ],
)
def test_input_validators_reject_invalid_values_with_fixed_messages(
    invoke: Callable[[], object],
) -> None:
    with pytest.raises(ValueError) as exc_info:
        invoke()

    assert "123456789" not in str(exc_info.value)
    assert "spark sql" not in str(exc_info.value)


def test_opaque_ids_preserve_url_syntax_and_encode_as_one_path_segment() -> None:
    opaque_id = "../folder?x=1#片段"

    assert validate_opaque_id(opaque_id, max_chars=64) == opaque_id
    assert encode_opaque_id(opaque_id, max_chars=64) == "..%2Ffolder%3Fx%3D1%23%E7%89%87%E6%AE%B5"


@pytest.mark.parametrize("value", ["", "id\nnext", "id\x00next", "x" * 513])
def test_opaque_ids_reject_empty_control_or_oversized_values(value: str) -> None:
    with pytest.raises(ValueError) as exc_info:
        validate_opaque_id(value, max_chars=512)

    # An empty string is trivially a substring of any message; the intent is
    # that non-empty rejected values are never echoed back.
    if value:
        assert value not in str(exc_info.value)


@pytest.mark.parametrize(
    ("upstream", "expected"),
    [
        ("READY", ParagraphStatus.PENDING),
        (" pending ", ParagraphStatus.PENDING),
        ("running", ParagraphStatus.RUNNING),
        ("FINISHED", ParagraphStatus.FINISHED),
        ("ERROR", ParagraphStatus.ERROR),
        ("ABORT", ParagraphStatus.CANCELLED),
        ("ABORTED", ParagraphStatus.CANCELLED),
        ("CANCEL", ParagraphStatus.CANCELLED),
        ("CANCELLED", ParagraphStatus.CANCELLED),
        ("future-state", ParagraphStatus.UNKNOWN),
        (None, ParagraphStatus.UNKNOWN),
        (123, ParagraphStatus.UNKNOWN),
    ],
)
def test_status_normalization_uses_the_closed_mapping(
    upstream: object, expected: ParagraphStatus
) -> None:
    assert normalize_paragraph_status(upstream) is expected


def test_all_public_results_are_typed_and_json_serializable() -> None:
    create = CreateNotebookResult(notebook_id="note/1", name="Daily")
    add = AddParagraphResult(
        notebook_id="note/1",
        paragraph_id="paragraph?1",
        title="Query",
        interpreter="spark.sql",
    )
    run = RunParagraphResult(
        notebook_id="note/1",
        paragraph_id="paragraph?1",
        status=ParagraphStatus.RUNNING,
    )
    status = ParagraphStatusResult(
        notebook_id="note/1",
        paragraph_id="paragraph?1",
        status=ParagraphStatus.FINISHED,
    )
    result = ParagraphResult(
        notebook_id="note/1",
        paragraph_id="paragraph?1",
        status=ParagraphStatus.FINISHED,
        outputs=(OutputItem(kind=OutputKind.TABLE, text="a\n1"),),
        error=None,
        truncated=False,
    )

    assert create.model_dump(mode="json") == {"notebook_id": "note/1", "name": "Daily"}
    assert add.model_dump(mode="json") == {
        "notebook_id": "note/1",
        "paragraph_id": "paragraph?1",
        "title": "Query",
        "interpreter": "spark.sql",
    }
    assert run.model_dump(mode="json")["status"] == "RUNNING"
    assert status.model_dump(mode="json")["status"] == "FINISHED"
    assert result.model_dump(mode="json") == {
        "notebook_id": "note/1",
        "paragraph_id": "paragraph?1",
        "status": "FINISHED",
        "outputs": [{"kind": "TABLE", "text": "a\n1"}],
        "error": None,
        "truncated": False,
    }


def test_error_result_contains_only_bounded_safe_detail() -> None:
    result = ParagraphResult(
        notebook_id="note-1",
        paragraph_id="paragraph-1",
        status=ParagraphStatus.ERROR,
        outputs=(),
        error=SafeErrorDetail(message="Execution failed."),
        truncated=False,
    )

    assert result.model_dump(mode="json")["error"] == {"message": "Execution failed."}
    assert set(SafeErrorDetail.model_fields) == {"message"}


@pytest.mark.parametrize(
    "construct",
    [
        lambda: ParagraphResult(
            notebook_id="note",
            paragraph_id="paragraph",
            status=ParagraphStatus.RUNNING,
            outputs=(),
            error=None,
            truncated=False,
        ),
        lambda: ParagraphResult(
            notebook_id="note",
            paragraph_id="paragraph",
            status=ParagraphStatus.FINISHED,
            outputs=(),
            error=SafeErrorDetail(message="not allowed"),
            truncated=False,
        ),
        lambda: ParagraphResult(
            notebook_id="note",
            paragraph_id="paragraph",
            status=ParagraphStatus.ERROR,
            outputs=(OutputItem(kind=OutputKind.TEXT, text="not allowed"),),
            error=SafeErrorDetail(message="failed"),
            truncated=False,
        ),
        lambda: ParagraphResult(
            notebook_id="note",
            paragraph_id="paragraph",
            status=ParagraphStatus.CANCELLED,
            outputs=(),
            error=None,
            truncated=False,
        ),
    ],
)
def test_paragraph_result_rejects_inconsistent_states(
    construct: Callable[[], object],
) -> None:
    with pytest.raises(ValidationError):
        construct()


def test_models_are_strict_frozen_and_reject_unknown_or_sensitive_fields() -> None:
    result = CreateNotebookResult(notebook_id="note", name="Daily")

    with pytest.raises(ValidationError):
        result.name = "changed"
    with pytest.raises(ValidationError):
        CreateNotebookResult.model_validate({"notebook_id": "note", "name": 123})
    with pytest.raises(ValidationError):
        CreateNotebookResult.model_validate(
            {"notebook_id": "note", "name": "Daily", "cookie": "not allowed"}
        )

    public_fields = {
        *CreateNotebookResult.model_fields,
        *AddParagraphResult.model_fields,
        *RunParagraphResult.model_fields,
        *ParagraphStatusResult.model_fields,
        *OutputItem.model_fields,
        *SafeErrorDetail.model_fields,
        *ParagraphResult.model_fields,
    }
    assert public_fields.isdisjoint(
        {"authorization", "cookie", "credentials", "headers", "password", "token", "username"}
    )


def test_output_and_error_text_use_utf8_byte_bounds() -> None:
    with pytest.raises(ValidationError):
        OutputItem(kind=OutputKind.TEXT, text="你" * 349_526)
    with pytest.raises(ValidationError):
        SafeErrorDetail(message="你" * 1_366)


def test_utf8_truncation_never_returns_partial_characters() -> None:
    assert truncate_utf8("ab你cd", max_bytes=5) == ("ab你", True)
    assert truncate_utf8("ab你", max_bytes=5) == ("ab你", False)


def test_notebook_tree_node_builds_from_flat_paths() -> None:
    from mcp_stdio.plugins.zeppelin.models import build_notebook_tree

    entries = [
        ("nb-1", "/team/note-a"),
        ("nb-2", "/team/note-b"),
        ("nb-3", "/Untitled Note"),
    ]
    tree = build_notebook_tree(entries)

    assert isinstance(tree, tuple)
    # Root should have "team" folder and "Untitled Note" leaf
    root_names = {node.name for node in tree}
    assert root_names == {"team", "Untitled Note"}

    team = next(n for n in tree if n.name == "team")
    assert team.notebook_id is None
    assert len(team.children) == 2
    child_names = {c.name for c in team.children}
    assert child_names == {"note-a", "note-b"}
    for child in team.children:
        assert child.notebook_id is not None
        assert child.children == ()

    untitled = next(n for n in tree if n.name == "Untitled Note")
    assert untitled.notebook_id == "nb-3"
    assert untitled.children == ()


def test_notebook_tree_node_empty_list() -> None:
    from mcp_stdio.plugins.zeppelin.models import build_notebook_tree

    assert build_notebook_tree(()) == ()


def test_notebook_tree_node_is_frozen_and_json_serializable() -> None:
    from mcp_stdio.plugins.zeppelin.models import build_notebook_tree

    tree = build_notebook_tree((("nb-1", "/a/b"),))
    data = [node.model_dump(mode="json") for node in tree]
    assert data[0]["name"] == "a"
    assert data[0]["notebook_id"] is None
    assert data[0]["children"][0]["notebook_id"] == "nb-1"
