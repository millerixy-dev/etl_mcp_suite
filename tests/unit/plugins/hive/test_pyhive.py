"""PyHive adapter contract and resource-lifecycle tests."""

from __future__ import annotations

import asyncio
import inspect
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import pytest
from pydantic import SecretStr
from pyhive.exc import (  # pyright: ignore[reportMissingTypeStubs]
    InterfaceError,
    OperationalError,
)
from thrift.transport.TTransport import (  # pyright: ignore[reportMissingTypeStubs]
    TTransportException,
)

from mcp_stdio.core.errors import ErrorCategory, ToolOperation
from mcp_stdio.plugins.hive.config import HiveSecrets, HiveSettings
from mcp_stdio.plugins.hive.gateway import HiveGatewayError, HiveMetadataGateway
from mcp_stdio.plugins.hive.pyhive import PyHiveMetadataAdapter


@dataclass(frozen=True, slots=True)
class FakeStatus:
    sqlState: str | None = None


@dataclass(frozen=True, slots=True)
class FakeResponse:
    status: FakeStatus


class FakeCursor:
    def __init__(
        self,
        *,
        rows: object = (("value",),),
        execute_error: Exception | None = None,
        fetch_error: Exception | None = None,
        close_error: Exception | None = None,
        events: list[tuple[str, int]] | None = None,
    ) -> None:
        self.rows = rows
        self.execute_error = execute_error
        self.fetch_error = fetch_error
        self.close_error = close_error
        self.events = [] if events is None else events
        self.statements: list[str] = []
        self.close_calls = 0

    def execute(self, statement: str) -> None:
        self.events.append(("execute", threading.get_ident()))
        self.statements.append(statement)
        if self.execute_error is not None:
            raise self.execute_error

    def fetchall(self) -> object:
        self.events.append(("fetchall", threading.get_ident()))
        if self.fetch_error is not None:
            raise self.fetch_error
        return self.rows

    def close(self) -> None:
        self.events.append(("cursor.close", threading.get_ident()))
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


class FakeConnection:
    def __init__(
        self,
        cursor: FakeCursor,
        *,
        cursor_error: Exception | None = None,
        close_error: Exception | None = None,
        events: list[tuple[str, int]] | None = None,
    ) -> None:
        self.cursor_error = cursor_error
        self.close_error = close_error
        self.events = cursor.events if events is None else events
        self.cursor_calls = 0
        self.close_calls = 0
        self.cursor_instance = cursor

    def cursor(self) -> FakeCursor:
        self.events.append(("cursor", threading.get_ident()))
        self.cursor_calls += 1
        if self.cursor_error is not None:
            raise self.cursor_error
        return self.cursor_instance

    def close(self) -> None:
        self.events.append(("connection.close", threading.get_ident()))
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


class RecordingFactory:
    def __init__(
        self,
        connection_builder: Callable[[], FakeConnection],
        *,
        error: Exception | None = None,
        events: list[tuple[str, int]] | None = None,
    ) -> None:
        self.connection_builder = connection_builder
        self.error = error
        self.events = [] if events is None else events
        self.calls: list[dict[str, object]] = []
        self.connections: list[FakeConnection] = []

    def __call__(self, **kwargs: object) -> FakeConnection:
        self.events.append(("connect", threading.get_ident()))
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        connection = self.connection_builder()
        self.connections.append(connection)
        return connection


def adapter_with(
    factory: RecordingFactory,
    *,
    username: str = "ldap-user-sentinel",
    password: str = "ldap-password-sentinel",
) -> PyHiveMetadataAdapter:
    return PyHiveMetadataAdapter(
        settings=HiveSettings(
            host="hive.example.internal",
            port=10_001,
            database="catalog",
            cache_ttl_seconds=30,
        ),
        secrets=HiveSecrets(
            username=SecretStr(username),
            password=SecretStr(password),
        ),
        connection_factory=factory,
    )


def successful_factory(
    rows: object = (("value",),),
    *,
    events: list[tuple[str, int]] | None = None,
) -> RecordingFactory:
    shared_events = [] if events is None else events

    def build() -> FakeConnection:
        return FakeConnection(FakeCursor(rows=rows, events=shared_events), events=shared_events)

    return RecordingFactory(build, events=shared_events)


async def test_adapter_generates_only_four_fixed_statement_families() -> None:
    factory = successful_factory(rows=[["metadata"]])
    adapter = adapter_with(factory)

    databases = await adapter.list_databases()
    tables = await adapter.list_tables("Analytics")
    describe = await adapter.describe_table("Analytics", "Daily_Events")
    ddl = await adapter.show_create_table("Analytics", "Daily_Events")

    assert databases == tables == describe == ddl == (("metadata",),)
    assert [connection.cursor_instance.statements for connection in factory.connections] == [
        ["SHOW DATABASES"],
        ["SHOW TABLES IN `Analytics`"],
        ["DESCRIBE `Analytics`.`Daily_Events`"],
        ["SHOW CREATE TABLE `Analytics`.`Daily_Events`"],
    ]
    assert factory.calls == [
        {
            "host": "hive.example.internal",
            "port": 10_001,
            "database": "catalog",
            "username": "ldap-user-sentinel",
            "password": "ldap-password-sentinel",
            "auth": "LDAP",
        }
    ] * 4
    assert all(connection.cursor_calls == 1 for connection in factory.connections)
    assert all(
        connection.cursor_instance.close_calls == 1
        for connection in factory.connections
    )
    assert all(connection.close_calls == 1 for connection in factory.connections)


def test_adapter_public_api_has_no_caller_sql_or_statement_arguments() -> None:
    assert tuple(inspect.signature(PyHiveMetadataAdapter.list_databases).parameters) == (
        "self",
    )
    assert tuple(inspect.signature(PyHiveMetadataAdapter.list_tables).parameters) == (
        "self",
        "database",
    )
    assert tuple(inspect.signature(PyHiveMetadataAdapter.describe_table).parameters) == (
        "self",
        "database",
        "table",
    )
    assert tuple(inspect.signature(PyHiveMetadataAdapter.show_create_table).parameters) == (
        "self",
        "database",
        "table",
    )


def invoke_unsafe_database(adapter: PyHiveMetadataAdapter) -> Awaitable[object]:
    return adapter.list_tables("sales data")


def invoke_unsafe_table(adapter: PyHiveMetadataAdapter) -> Awaitable[object]:
    return adapter.describe_table("default", "events; DROP TABLE users")


def invoke_unsafe_qualified_database(
    adapter: PyHiveMetadataAdapter,
) -> Awaitable[object]:
    return adapter.show_create_table("bad.db", "events")


@pytest.mark.parametrize(
    ("invoke", "operation"),
    [
        (invoke_unsafe_database, ToolOperation.LIST_TABLES),
        (invoke_unsafe_table, ToolOperation.GET_TABLE_SCHEMA),
        (invoke_unsafe_qualified_database, ToolOperation.GET_TABLE_SCHEMA),
    ],
)
async def test_unsafe_identifier_is_rejected_before_connection_creation(
    invoke: Callable[[PyHiveMetadataAdapter], Awaitable[object]],
    operation: ToolOperation,
) -> None:
    factory = successful_factory()
    adapter = adapter_with(factory)

    with pytest.raises(HiveGatewayError) as captured:
        await invoke(adapter)

    assert captured.value.tool_error.category is ErrorCategory.INVALID_INPUT
    assert captured.value.tool_error.operation is operation
    assert captured.value.tool_error.identifiers == {}
    assert factory.calls == []


async def test_complete_blocking_lifecycle_runs_in_one_worker_thread() -> None:
    events: list[tuple[str, int]] = []
    factory = successful_factory(events=events)
    adapter = adapter_with(factory)
    event_loop_thread = threading.get_ident()

    await adapter.list_databases()

    assert [name for name, _ in events] == [
        "connect",
        "cursor",
        "execute",
        "fetchall",
        "cursor.close",
        "connection.close",
    ]
    assert len({thread_id for _, thread_id in events}) == 1
    assert events[0][1] != event_loop_thread


async def test_concurrent_invocations_use_independent_connections() -> None:
    factory = successful_factory()
    adapter = adapter_with(factory)

    await asyncio.gather(
        adapter.list_databases(),
        adapter.list_tables("default"),
        adapter.describe_table("default", "events"),
    )

    assert len(factory.calls) == 3
    assert len(factory.connections) == 3
    assert len({id(connection) for connection in factory.connections}) == 3
    assert all(connection.close_calls == 1 for connection in factory.connections)


@pytest.mark.parametrize("failure_stage", ["connect", "cursor", "execute", "fetchall"])
async def test_primary_failure_closes_every_created_resource(failure_stage: str) -> None:
    secret = "secret-must-not-cross-error-boundary"
    stage_error = RuntimeError(secret)
    cursor = FakeCursor(
        execute_error=stage_error if failure_stage == "execute" else None,
        fetch_error=stage_error if failure_stage == "fetchall" else None,
    )
    connection = FakeConnection(
        cursor,
        cursor_error=stage_error if failure_stage == "cursor" else None,
    )
    factory = RecordingFactory(
        lambda: connection,
        error=stage_error if failure_stage == "connect" else None,
    )
    adapter = adapter_with(factory, password=secret)

    with pytest.raises(HiveGatewayError) as captured:
        await adapter.list_databases()

    assert captured.value.tool_error.category is ErrorCategory.UPSTREAM_ERROR
    assert secret not in str(captured.value)
    assert secret not in repr(captured.value.tool_error.to_dict(secret_values=(secret,)))
    assert cursor.close_calls == (1 if failure_stage in {"execute", "fetchall"} else 0)
    assert connection.close_calls == (0 if failure_stage == "connect" else 1)


@pytest.mark.parametrize("close_stage", ["cursor", "connection"])
async def test_close_failure_after_success_is_mapped_and_other_resource_is_closed(
    close_stage: str,
) -> None:
    cursor = FakeCursor(
        close_error=RuntimeError("cursor-close-secret") if close_stage == "cursor" else None
    )
    connection = FakeConnection(
        cursor,
        close_error=(
            RuntimeError("connection-close-secret")
            if close_stage == "connection"
            else None
        ),
    )
    adapter = adapter_with(RecordingFactory(lambda: connection))

    with pytest.raises(HiveGatewayError) as captured:
        await adapter.list_databases()

    assert captured.value.tool_error.category is ErrorCategory.UPSTREAM_ERROR
    assert "secret" not in str(captured.value)
    assert cursor.close_calls == 1
    assert connection.close_calls == 1


async def test_cleanup_failure_does_not_mask_primary_failure() -> None:
    primary = OperationalError(FakeResponse(FakeStatus(sqlState="42501")))
    cursor = FakeCursor(
        execute_error=primary,
        close_error=RuntimeError("cursor-close-secret"),
    )
    connection = FakeConnection(
        cursor,
        close_error=RuntimeError("connection-close-secret"),
    )
    adapter = adapter_with(RecordingFactory(lambda: connection))

    with pytest.raises(HiveGatewayError) as captured:
        await adapter.list_databases()

    assert captured.value.tool_error.category is ErrorCategory.PERMISSION_DENIED
    assert cursor.close_calls == connection.close_calls == 1


@pytest.mark.parametrize(
    ("connection_error", "expected_category"),
    [
        (
            TTransportException(
                type=TTransportException.NOT_OPEN,
                message="ldap-rejection-secret",
            ),
            ErrorCategory.AUTHENTICATION_FAILED,
        ),
        (
            TTransportException(
                type=TTransportException.NOT_OPEN,
                message="connection-secret",
                inner=ConnectionRefusedError(),
            ),
            ErrorCategory.CONNECTION_FAILED,
        ),
    ],
)
async def test_connect_transport_failure_uses_safe_inner_exception_policy(
    connection_error: Exception,
    expected_category: ErrorCategory,
) -> None:
    factory = RecordingFactory(
        lambda: FakeConnection(FakeCursor()),
        error=connection_error,
    )
    adapter = adapter_with(factory)

    with pytest.raises(HiveGatewayError) as captured:
        await adapter.list_databases()

    assert captured.value.tool_error.category is expected_category
    assert "secret" not in str(captured.value)


@pytest.mark.parametrize(
    ("upstream_error", "expected_category", "retryable"),
    [
        (
            OperationalError(FakeResponse(FakeStatus(sqlState="28000"))),
            ErrorCategory.AUTHENTICATION_FAILED,
            False,
        ),
        (
            OperationalError(FakeResponse(FakeStatus(sqlState="42501"))),
            ErrorCategory.PERMISSION_DENIED,
            False,
        ),
        (
            OperationalError(FakeResponse(FakeStatus(sqlState="42S02"))),
            ErrorCategory.NOT_FOUND,
            False,
        ),
        (
            OperationalError(FakeResponse(FakeStatus(sqlState="HYT00"))),
            ErrorCategory.TIMEOUT,
            True,
        ),
        (
            OperationalError(FakeResponse(FakeStatus(sqlState="08006"))),
            ErrorCategory.CONNECTION_FAILED,
            True,
        ),
        (
            OperationalError(FakeResponse(FakeStatus(sqlState="HY000"))),
            ErrorCategory.UPSTREAM_ERROR,
            False,
        ),
        (TimeoutError("timeout-secret"), ErrorCategory.TIMEOUT, True),
        (InterfaceError("interface-secret"), ErrorCategory.CONNECTION_FAILED, True),
        (
            TTransportException(
                type=TTransportException.NOT_OPEN,
                message="transport-secret",
            ),
            ErrorCategory.CONNECTION_FAILED,
            True,
        ),
    ],
)
async def test_upstream_failures_are_mapped_by_type_or_sqlstate_without_raw_text(
    upstream_error: Exception,
    expected_category: ErrorCategory,
    retryable: bool,
) -> None:
    cursor = FakeCursor(execute_error=upstream_error)
    adapter = adapter_with(RecordingFactory(lambda: FakeConnection(cursor)))

    with pytest.raises(HiveGatewayError) as captured:
        await adapter.describe_table("default", "events")

    error = captured.value.tool_error
    assert error.category is expected_category
    assert error.operation is ToolOperation.GET_TABLE_SCHEMA
    assert error.retryable is retryable
    assert error.identifiers == {"database": "default", "table": "events"}
    assert "secret" not in str(captured.value)
    assert "secret" not in repr(error.to_dict(secret_values=("secret",)))


@pytest.mark.parametrize(
    "rows",
    [None, 7, "not-row-collection", ["not-a-row"], [("valid",), object()]],
)
async def test_non_row_fetch_results_map_to_unexpected_response(rows: object) -> None:
    factory = successful_factory(rows=rows)
    adapter = adapter_with(factory)

    with pytest.raises(HiveGatewayError) as captured:
        await adapter.list_databases()

    assert captured.value.tool_error.category is ErrorCategory.UNEXPECTED_RESPONSE
    assert factory.connections[0].cursor_instance.close_calls == 1
    assert factory.connections[0].close_calls == 1


def test_adapter_satisfies_mcp_independent_gateway_protocol() -> None:
    adapter: HiveMetadataGateway = adapter_with(successful_factory())

    assert adapter is not None
