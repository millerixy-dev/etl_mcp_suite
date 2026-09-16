"""Isolated, network-free tests of the one-query Zeppelin WebSocket adapter."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager

import pytest
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosedError, InvalidHandshake, InvalidStatus
from websockets.frames import Close
from websockets.http11 import Response

from mcp_stdio.core.errors import ErrorCategory, ToolOperation
from mcp_stdio.plugins.zeppelin.gateway import ZeppelinGatewayError
from mcp_stdio.plugins.zeppelin.models import InterpreterBindingRecord
from mcp_stdio.plugins.zeppelin.websocket_client import SingleQueryConnection, query_bindings


class FakeConnection:
    def __init__(self, frames: Sequence[str | bytes | Exception]) -> None:
        self.frames = list(frames)
        self.sent: list[str] = []
        self.received = 0
        self.closed = False
        self.send_failure: Exception | None = None

    async def send(self, message: str) -> None:
        self.sent.append(message)
        if self.send_failure is not None:
            raise self.send_failure

    async def recv(self) -> str | bytes:
        self.received += 1
        frame = self.frames.pop(0)
        if isinstance(frame, Exception):
            raise frame
        return frame


class FakeConnector:
    def __init__(self, frames: Sequence[str | bytes | Exception]) -> None:
        self.connection = FakeConnection(frames)
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.failure: Exception | None = None

    @asynccontextmanager
    async def __call__(self, url: str, **options: object) -> AsyncGenerator[FakeConnection, None]:
        self.calls.append((url, options))
        if self.failure is not None:
            raise self.failure
        try:
            yield self.connection
        finally:
            self.connection.closed = True


def binding(**overrides: object) -> dict[str, object]:
    return {
        "id": "spark-setting",
        "name": "Spark production",
        "interpreters": [{"name": "sql"}, {"name": "spark"}],
        "selected": True,
        **overrides,
    }


def response(bindings: object) -> str:
    return json.dumps(
        {"op": "INTERPRETER_BINDINGS", "data": {"interpreterBindings": bindings}},
        ensure_ascii=False,
        separators=(",", ":"),
    )


async def query(
    connector: FakeConnector,
    *,
    max_response_bytes: int = 1_048_576,
    max_opaque_id_chars: int = 512,
    operation: ToolOperation = ToolOperation.GET_INTERPRETER_BINDINGS,
    identifiers: dict[str, str] | None = None,
    cookie_header: str | None = "session=fake-cookie",
) -> tuple[InterpreterBindingRecord, ...]:
    return await query_bindings(
        url="wss://zep.example:9443/proxy/ws",
        origin="https://zep.example:9443",
        principal="fake-principal",
        ticket="fake-ticket",
        roles='["reader"]',
        cookie_header=cookie_header,
        notebook_id="123/note ?#",
        max_response_bytes=max_response_bytes,
        max_opaque_id_chars=max_opaque_id_chars,
        request_timeout_seconds=3.0,
        operation=operation,
        identifiers={"notebook_id": "123/note ?#"} if identifiers is None else identifiers,
        connector=connector,
        msg_id_factory=lambda: "deterministic-id",
    )


async def test_exact_request_accepts_uncorrelated_response_and_discards_extra_fields() -> None:
    connector = FakeConnector([response([
        binding(properties={"password": "discarded"}, group="discarded"),
        binding(id="1/reserved?%", name="Second", interpreters=[], selected=False),
    ])])
    result = await query(connector)
    assert connector.connection.sent == [
        '{"op":"GET_INTERPRETER_BINDINGS","data":{"noteId":"123/note ?#"},'
        '"principal":"fake-principal","ticket":"fake-ticket",'
        '"roles":"[\\"reader\\"]","msgId":"deterministic-id"}'
    ]
    assert [item.model_dump(mode="json") for item in result] == [
        {"setting_id": "spark-setting", "name": "Spark production",
         "interpreters": ["sql", "spark"], "selected": True},
        {"setting_id": "1/reserved?%", "name": "Second", "interpreters": [], "selected": False},
    ]
    assert isinstance(result, tuple)
    assert connector.connection.closed


@pytest.mark.parametrize("cookie_header", [None, "session=fake-cookie"])
async def test_connector_uses_private_silent_logger_and_only_scoped_cookie(
    cookie_header: str | None, caplog: pytest.LogCaptureFixture,
) -> None:
    connector = FakeConnector([response([])])
    assert await query(connector, cookie_header=cookie_header) == ()
    assert len(connector.calls) == 1
    url, options = connector.calls[0]
    assert url == "wss://zep.example:9443/proxy/ws"
    assert options["origin"] == "https://zep.example:9443"
    assert options["additional_headers"] == (
        None if cookie_header is None else {"Cookie": cookie_header}
    )
    assert options["proxy"] is None
    assert options["compression"] is None
    assert options["max_queue"] == 1
    assert options["max_size"] == 1_048_576
    assert options["open_timeout"] == 3.0
    assert options["close_timeout"] == 3.0
    assert "ssl" not in options  # Library TLS verification remains enabled.
    logger = options["logger"]
    assert isinstance(logger, logging.Logger)
    with caplog.at_level(logging.DEBUG):
        logger.debug("fake-ticket")
        logger.error("fake-cookie")
    assert caplog.text == ""


@pytest.mark.parametrize("field", ["id", "name", "interpreters", "selected"])
async def test_missing_required_binding_fields_fail(field: str) -> None:
    item = binding()
    del item[field]
    await assert_unexpected([response([item])])


@pytest.mark.parametrize("value", [None, True, 1, 1.5, [], {}, "", "bad\n", "bad\x7f"])
@pytest.mark.parametrize("field", ["id", "name"])
async def test_binding_text_is_strict(field: str, value: object) -> None:
    await assert_unexpected([response([binding(**{field: value})])])


@pytest.mark.parametrize("value", [None, 0, 1, "true", "false", [], {}])
async def test_selected_is_strict_boolean(value: object) -> None:
    await assert_unexpected([response([binding(selected=value)])])


@pytest.mark.parametrize("value", [None, {}, "sql", [None], ["sql"], [{}], [{"name": None}],
                                   [{"name": 1}], [{"name": True}], [{"name": ""}],
                                   [{"name": "bad\n"}], [{"name": "bad\x7f"}],
                                   [{"name": "n" * 257}], [{"name": "sql"}] * 65])
async def test_interpreters_require_bounded_array_of_strict_name_objects(value: object) -> None:
    await assert_unexpected([response([binding(interpreters=value)])])


@pytest.mark.parametrize("items", [None, {}, "bindings", [None], [True], ["setting"],
                                  [binding(), binding()],
                                  [binding(id=str(i)) for i in range(257)],
                                  [binding(name="n" * 257)], [binding(id="i" * 513)]])
async def test_invalid_binding_collections_fail_without_partial_results(items: object) -> None:
    await assert_unexpected([response(items)])


async def test_exact_collection_and_name_limits_are_accepted_in_upstream_order() -> None:
    items = [binding(id=f"id-{i}", name="n" * 256,
                     interpreters=[{"name": "n" * 256, "className": "discard"}] * 64)
             for i in range(256)]
    connector = FakeConnector([response(items)])
    result = await query(connector, max_response_bytes=8_388_608)
    assert [record.setting_id for record in result] == [f"id-{i}" for i in range(256)]
    assert result[0].interpreters == ("n" * 256,) * 64


async def test_setting_id_uses_configured_limit_without_trimming_or_encoding() -> None:
    connector = FakeConnector([response([binding(id="x" * 512)])])
    assert (await query(connector))[0].setting_id == "x" * 512
    with pytest.raises(ZeppelinGatewayError) as error:
        await query(FakeConnector([response([binding(id="abc")])]), max_opaque_id_chars=2)
    assert error.value.tool_error.category == ErrorCategory.UNEXPECTED_RESPONSE


@pytest.mark.parametrize("frame", [b"{}", "not json", "[]", "null", "true", "1", '"text"',
                                  "{}", '{"op":1,"data":{}}', '{"op":null,"data":{}}',
                                  '{"op":"OTHER"}', '{"op":"OTHER","data":null}',
                                  '{"op":"OTHER","data":[]}',
                                  '{"op":"INTERPRETER_BINDINGS"}',
                                  '{"op":"INTERPRETER_BINDINGS","data":{}}',
                                  '{"op":"INTERPRETER_BINDINGS","data":[]}'])
async def test_malformed_application_frames_fail(frame: str | bytes) -> None:
    await assert_unexpected([frame])


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
async def test_non_json_numeric_constants_are_rejected_even_in_extra_fields(
    constant: str,
) -> None:
    frame = '{"op":"INTERPRETER_BINDINGS","data":{"interpreterBindings":[]},"extra":'
    await assert_unexpected([frame + constant + "}"])


async def assert_unexpected(frames: list[str | bytes | Exception]) -> None:
    connector = FakeConnector(frames)
    with pytest.raises(ZeppelinGatewayError) as error:
        await query(connector)
    assert error.value.tool_error.category == ErrorCategory.UNEXPECTED_RESPONSE
    assert error.value.tool_error.retryable is False
    assert connector.connection.closed


async def test_final_response_can_be_the_32nd_frame() -> None:
    connector = FakeConnector(['{"op":"OTHER","data":{}}'] * 31 + [response([])])
    assert await query(connector) == ()
    assert connector.connection.received == 32


async def test_33rd_frame_is_never_received() -> None:
    connector = FakeConnector(['{"op":"OTHER","data":{}}'] * 32 + [response([])])
    with pytest.raises(ZeppelinGatewayError) as error:
        await query(connector)
    assert error.value.tool_error.category == ErrorCategory.UNEXPECTED_RESPONSE
    assert connector.connection.received == 32
    assert connector.connection.closed


@pytest.mark.parametrize("extra", [0, 1])
@pytest.mark.parametrize("unrelated", [False, True])
async def test_frame_and_cumulative_limits_count_utf8_bytes(extra: int, unrelated: bool) -> None:
    final = response([binding(name="中文")])
    frames = (['{"op":"OTHER","data":{"text":"中文"}}'] if unrelated else []) + [final]
    size = sum(len(frame.encode("utf-8")) for frame in frames)
    connector = FakeConnector(frames)
    if extra:
        with pytest.raises(ZeppelinGatewayError) as error:
            await query(connector, max_response_bytes=size - 1)
        assert error.value.tool_error.category == ErrorCategory.UNEXPECTED_RESPONSE
    else:
        assert (await query(connector, max_response_bytes=size))[0].name == "中文"
    assert connector.connection.closed


@pytest.mark.parametrize(("op", "category"), [
    ("AUTH_INFO", ErrorCategory.AUTHENTICATION_FAILED),
    ("SESSION_LOGOUT", ErrorCategory.AUTHENTICATION_FAILED),
    ("ERROR_INFO", ErrorCategory.UPSTREAM_ERROR),
])
async def test_error_operations_have_safe_non_retryable_errors(
    op: str, category: ErrorCategory,
) -> None:
    connector = FakeConnector([json.dumps({"op": op, "data": {"message": "fake-ticket"}})])
    with pytest.raises(ZeppelinGatewayError) as error:
        await query(connector)
    assert error.value.tool_error.category == category
    assert error.value.tool_error.retryable is False
    assert "fake-ticket" not in str(error.value)
    assert error.value.__suppress_context__


def handshake(status: int) -> InvalidStatus:
    return InvalidStatus(Response(status, "fake-ticket", Headers(), body=b"fake-cookie"))


@pytest.mark.parametrize(("status", "category"), [
    (401, ErrorCategory.AUTHENTICATION_FAILED), (403, ErrorCategory.PERMISSION_DENIED),
    (404, ErrorCategory.UPSTREAM_ERROR), (500, ErrorCategory.UPSTREAM_ERROR),
    (302, ErrorCategory.UPSTREAM_ERROR),
])
async def test_handshake_failures_do_not_reconnect_or_expose_upstream_text(
    status: int, category: ErrorCategory,
) -> None:
    connector = FakeConnector([])
    connector.failure = handshake(status)
    with pytest.raises(ZeppelinGatewayError) as error:
        await query(connector)
    assert error.value.tool_error.category == category
    assert error.value.tool_error.retryable is False
    assert len(connector.calls) == 1
    assert "fake-ticket" not in repr(error.value.tool_error)
    assert "fake-cookie" not in str(error.value)


@pytest.mark.parametrize("operation", [ToolOperation.GET_INTERPRETER_BINDINGS,
                                       ToolOperation.RESTART_INTERPRETER])
@pytest.mark.parametrize("stage", ["connect", "send", "receive"])
@pytest.mark.parametrize(("failure", "category"), [
    (OSError("fake-ticket"), ErrorCategory.CONNECTION_FAILED),
    (TimeoutError("fake-ticket"), ErrorCategory.TIMEOUT),
    (ConnectionClosedError(None, None), ErrorCategory.CONNECTION_FAILED),
    (InvalidHandshake("fake-ticket"), ErrorCategory.CONNECTION_FAILED),
])
async def test_transport_failure_mapping_and_safe_operation_context(
    operation: ToolOperation, stage: str, failure: Exception, category: ErrorCategory,
) -> None:
    connector = FakeConnector([failure])
    if stage == "connect":
        connector.failure = failure
    elif stage == "send":
        connector.connection.send_failure = failure
    with pytest.raises(ZeppelinGatewayError) as error:
        await query(connector, operation=operation,
                    identifiers={"notebook_id": "x" * 257, "setting_id": "safe", "cookie": "no"})
    assert error.value.tool_error.operation == operation
    assert error.value.tool_error.category == category
    assert error.value.tool_error.identifiers == (
        {"setting_id": "safe"} if operation == ToolOperation.RESTART_INTERPRETER else {}
    )
    assert error.value.tool_error.retryable == (operation == ToolOperation.GET_INTERPRETER_BINDINGS)
    assert "fake-ticket" not in repr(error.value.tool_error)
    assert len(connector.calls) == 1
    assert connector.connection.closed == (stage != "connect")


async def test_library_message_size_close_is_an_unexpected_response() -> None:
    await assert_unexpected([ConnectionClosedError(None, Close(1009, "fake-ticket"))])


async def test_default_connector_rejects_redirect_without_opening_another_connection() -> None:
    connection = SingleQueryConnection("wss://zep.example/ws", proxy=None)
    failure = handshake(302)
    failure.response.headers["Location"] = "wss://other.example/ws"
    assert connection.process_redirect(failure) is failure
