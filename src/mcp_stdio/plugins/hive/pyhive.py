"""PyHive outbound adapter for the four approved metadata statements."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from typing import Literal, Protocol, cast

from pyhive import hive  # pyright: ignore[reportMissingTypeStubs]
from pyhive.exc import (  # pyright: ignore[reportMissingTypeStubs]
    DatabaseError,
    InterfaceError,
    OperationalError,
)
from thrift.transport.TTransport import (  # pyright: ignore[reportMissingTypeStubs]
    TTransportException,
)

from mcp_stdio.core.errors import ErrorCategory, ToolError, ToolOperation
from mcp_stdio.plugins.hive.config import HiveSecrets, HiveSettings
from mcp_stdio.plugins.hive.gateway import HiveGatewayError, HiveRows
from mcp_stdio.plugins.hive.identifiers import HiveIdentifier


class _Cursor(Protocol):
    def execute(self, statement: str) -> object: ...

    def fetchall(self) -> object: ...

    def close(self) -> object: ...


class _Connection(Protocol):
    def cursor(self) -> _Cursor: ...

    def close(self) -> object: ...


_ConnectionFactory = Callable[..., _Connection]
_FailurePhase = Literal["connect", "cursor", "execute", "fetch", "response", "close"]


class _HiveRowsShapeError(ValueError):
    """Internal marker for a fetch result that is not a row collection."""


def _snapshot_rows(raw_rows: object) -> HiveRows:
    if not isinstance(raw_rows, Sequence) or isinstance(
        raw_rows, (str, bytes, bytearray)
    ):
        raise _HiveRowsShapeError

    rows: list[tuple[object, ...]] = []
    try:
        for raw_row in cast(Sequence[object], raw_rows):
            if not isinstance(raw_row, Sequence) or isinstance(
                raw_row, (str, bytes, bytearray)
            ):
                raise _HiveRowsShapeError
            rows.append(tuple(cast(Sequence[object], raw_row)))
    except _HiveRowsShapeError:
        raise
    except Exception:
        raise _HiveRowsShapeError from None
    return tuple(rows)


def _sql_state(exception: OperationalError) -> str | None:
    try:
        if not exception.args:
            return None
        response = exception.args[0]
        status = getattr(response, "status", None)
        value = getattr(status, "sqlState", None)
    except Exception:
        return None
    if not (
        isinstance(value, str)
        and len(value) == 5
        and value.isascii()
        and value.isalnum()
    ):
        return None
    return value.upper()


def _category_for_exception(
    exception: Exception,
    *,
    phase: _FailurePhase,
) -> tuple[ErrorCategory, bool]:
    if isinstance(exception, _HiveRowsShapeError):
        return ErrorCategory.UNEXPECTED_RESPONSE, False
    if isinstance(exception, TimeoutError):
        return ErrorCategory.TIMEOUT, True
    if isinstance(exception, TTransportException):
        if exception.type == TTransportException.TIMED_OUT:
            return ErrorCategory.TIMEOUT, True
        transport_inner = cast(object | None, getattr(exception, "inner", None))
        if (
            phase == "connect"
            and exception.type == TTransportException.NOT_OPEN
            and transport_inner is None
        ):
            return ErrorCategory.AUTHENTICATION_FAILED, False
        return ErrorCategory.CONNECTION_FAILED, True
    if isinstance(exception, InterfaceError):
        return ErrorCategory.CONNECTION_FAILED, True
    if isinstance(exception, (ConnectionError, OSError)):
        return ErrorCategory.CONNECTION_FAILED, True
    if isinstance(exception, OperationalError):
        sql_state = _sql_state(exception)
        if sql_state is not None:
            if sql_state.startswith("28"):
                return ErrorCategory.AUTHENTICATION_FAILED, False
            if sql_state == "42501":
                return ErrorCategory.PERMISSION_DENIED, False
            if sql_state in {"42P01", "42S02"}:
                return ErrorCategory.NOT_FOUND, False
            if sql_state in {"HYT00", "HYT01"}:
                return ErrorCategory.TIMEOUT, True
            if sql_state.startswith("08"):
                return ErrorCategory.CONNECTION_FAILED, True
        return ErrorCategory.UPSTREAM_ERROR, False
    if isinstance(exception, DatabaseError):
        return ErrorCategory.UPSTREAM_ERROR, False
    return ErrorCategory.UPSTREAM_ERROR, False


def _gateway_error(
    exception: Exception,
    *,
    phase: _FailurePhase,
    operation: ToolOperation,
    identifiers: dict[str, str],
) -> HiveGatewayError:
    category, retryable = _category_for_exception(exception, phase=phase)
    return HiveGatewayError(
        ToolError.create(
            category=category,
            operation=operation,
            retryable=retryable,
            identifiers=identifiers,
        )
    )


def _validated_identifier(
    value: str,
    *,
    operation: ToolOperation,
) -> HiveIdentifier:
    try:
        return HiveIdentifier(value)
    except (TypeError, ValueError):
        raise HiveGatewayError(
            ToolError.create(
                category=ErrorCategory.INVALID_INPUT,
                operation=operation,
                retryable=False,
            )
        ) from None


class PyHiveMetadataAdapter:
    """Open one LDAP/binary PyHive connection per metadata invocation."""

    def __init__(
        self,
        *,
        settings: HiveSettings,
        secrets: HiveSecrets,
        connection_factory: _ConnectionFactory | None = None,
    ) -> None:
        self._settings = settings
        self._secrets = secrets
        self._connection_factory = (
            cast(
                _ConnectionFactory,
                hive.connect,  # pyright: ignore[reportUnknownMemberType]
            )
            if connection_factory is None
            else connection_factory
        )

    async def list_databases(self) -> HiveRows:
        return await self._execute(
            "SHOW DATABASES",
            operation=ToolOperation.LIST_DATABASES,
            identifiers={},
        )

    async def list_tables(self, database: str) -> HiveRows:
        database_identifier = _validated_identifier(
            database,
            operation=ToolOperation.LIST_TABLES,
        )
        return await self._execute(
            f"SHOW TABLES IN {database_identifier.quoted}",
            operation=ToolOperation.LIST_TABLES,
            identifiers={"database": database_identifier.value},
        )

    async def describe_table(self, database: str, table: str) -> HiveRows:
        database_identifier, table_identifier = self._validated_table(database, table)
        return await self._execute(
            f"DESCRIBE {database_identifier.quoted}.{table_identifier.quoted}",
            operation=ToolOperation.GET_TABLE_SCHEMA,
            identifiers={
                "database": database_identifier.value,
                "table": table_identifier.value,
            },
        )

    async def show_create_table(self, database: str, table: str) -> HiveRows:
        database_identifier, table_identifier = self._validated_table(database, table)
        return await self._execute(
            "SHOW CREATE TABLE "
            f"{database_identifier.quoted}.{table_identifier.quoted}",
            operation=ToolOperation.GET_TABLE_SCHEMA,
            identifiers={
                "database": database_identifier.value,
                "table": table_identifier.value,
            },
        )

    @staticmethod
    def _validated_table(
        database: str,
        table: str,
    ) -> tuple[HiveIdentifier, HiveIdentifier]:
        operation = ToolOperation.GET_TABLE_SCHEMA
        database_identifier = _validated_identifier(database, operation=operation)
        table_identifier = _validated_identifier(table, operation=operation)
        return database_identifier, table_identifier

    async def _execute(
        self,
        statement: str,
        *,
        operation: ToolOperation,
        identifiers: dict[str, str],
    ) -> HiveRows:
        return await asyncio.to_thread(
            self._execute_blocking,
            statement,
            operation,
            identifiers,
        )

    def _execute_blocking(
        self,
        statement: str,
        operation: ToolOperation,
        identifiers: dict[str, str],
    ) -> HiveRows:
        connection: _Connection | None = None
        cursor: _Cursor | None = None
        rows: HiveRows | None = None
        primary_failure: tuple[Exception, _FailurePhase] | None = None
        phase: _FailurePhase = "connect"

        try:
            connection = self._connection_factory(
                host=self._settings.host,
                port=self._settings.port,
                database=self._settings.database,
                username=self._secrets.username.get_secret_value(),
                password=self._secrets.password.get_secret_value(),
                auth="LDAP",
            )
            phase = "cursor"
            cursor = connection.cursor()
            phase = "execute"
            cursor.execute(statement)
            phase = "fetch"
            raw_rows = cursor.fetchall()
            phase = "response"
            rows = _snapshot_rows(raw_rows)
        except Exception as exception:
            primary_failure = (exception, phase)
        finally:
            if cursor is not None:
                try:
                    cursor.close()
                except Exception as exception:
                    if primary_failure is None:
                        primary_failure = (exception, "close")
            if connection is not None:
                try:
                    connection.close()
                except Exception as exception:
                    if primary_failure is None:
                        primary_failure = (exception, "close")

        if primary_failure is not None:
            exception, failure_phase = primary_failure
            raise _gateway_error(
                exception,
                phase=failure_phase,
                operation=operation,
                identifiers=identifiers,
            ) from None
        if rows is None:
            raise _gateway_error(
                _HiveRowsShapeError(),
                phase="response",
                operation=operation,
                identifiers=identifiers,
            ) from None
        return rows
