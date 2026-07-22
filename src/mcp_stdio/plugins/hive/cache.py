"""Plugin-local TTL/LRU cache for successful Hive metadata results."""

from __future__ import annotations

import math
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from threading import RLock
from typing import Literal, TypeAlias, TypeVar, cast

from mcp_stdio.plugins.hive.identifiers import HiveIdentifier
from mcp_stdio.plugins.hive.models import (
    ListDatabasesResult,
    ListTablesResult,
    TableSchemaResult,
)

MAX_CACHE_ENTRIES = 256

HiveCacheKey: TypeAlias = (
    tuple[Literal["list_databases"]]
    | tuple[Literal["list_tables"], str]
    | tuple[Literal["get_table_schema"], str, str, bool]
)
CacheableHiveResult: TypeAlias = (
    ListDatabasesResult | ListTablesResult | TableSchemaResult
)
CacheResultT = TypeVar(
    "CacheResultT", ListDatabasesResult, ListTablesResult, TableSchemaResult
)


def _normalized_identifier(value: str | None, field_name: str) -> str:
    if value is None:
        raise ValueError(f"{field_name} is required for this Hive cache key")
    return HiveIdentifier(value).value.casefold()


def make_hive_cache_key(
    tool_name: str,
    *,
    database: str | None = None,
    table: str | None = None,
    include_ddl: bool = False,
) -> HiveCacheKey:
    """Build a canonical key from one fixed Hive tool and its safe arguments."""

    if type(include_ddl) is not bool:
        raise TypeError("include_ddl must be a boolean")
    if tool_name == "list_databases":
        if database is not None or table is not None or include_ddl:
            raise ValueError("list_databases cache key does not accept arguments")
        return ("list_databases",)
    if tool_name == "list_tables":
        if table is not None or include_ddl:
            raise ValueError("list_tables cache key accepts only database")
        return ("list_tables", _normalized_identifier(database, "database"))
    if tool_name == "get_table_schema":
        return (
            "get_table_schema",
            _normalized_identifier(database, "database"),
            _normalized_identifier(table, "table"),
            include_ddl,
        )
    raise ValueError("unsupported Hive cache tool")


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    value: CacheableHiveResult
    expires_at: float


def _validated_key(key: object) -> HiveCacheKey:
    if not isinstance(key, tuple):
        raise ValueError("expected a canonical Hive cache key")
    raw_key = cast(tuple[object, ...], key)
    canonical: HiveCacheKey | None = None
    if raw_key == ("list_databases",):
        canonical = ("list_databases",)
    elif len(raw_key) == 2 and raw_key[0] == "list_tables":
        database = raw_key[1]
        if isinstance(database, str):
            try:
                canonical = make_hive_cache_key("list_tables", database=database)
            except ValueError:
                pass
    elif (
        len(raw_key) == 4
        and raw_key[0] == "get_table_schema"
    ):
        database, table, include_ddl = raw_key[1:]
        if (
            isinstance(database, str)
            and isinstance(table, str)
            and type(include_ddl) is bool
        ):
            try:
                canonical = make_hive_cache_key(
                    "get_table_schema",
                    database=database,
                    table=table,
                    include_ddl=include_ddl,
                )
            except ValueError:
                pass
    if canonical is None or canonical != raw_key:
        raise ValueError("expected a canonical Hive cache key")
    return canonical


def _validated_result(
    key: HiveCacheKey, value: object
) -> CacheableHiveResult:
    if type(value) not in (
        ListDatabasesResult,
        ListTablesResult,
        TableSchemaResult,
    ):
        raise TypeError(
            "cache loader must return a validated Hive metadata result; "
            "exact Hive metadata result type required"
        )
    if key[0] == "list_databases" and type(value) is ListDatabasesResult:
        return value
    if key[0] == "list_tables" and type(value) is ListTablesResult:
        tables_result = value
        if tables_result.database.casefold() == key[1]:
            return tables_result
    if key[0] == "get_table_schema" and type(value) is TableSchemaResult:
        schema_result = value
        if (
            schema_result.database.casefold() == key[1]
            and schema_result.table.casefold() == key[2]
            and (schema_result.ddl is not None) is key[3]
        ):
            return schema_result
    raise TypeError("cache loader result does not match Hive cache key")


def _with_cache_status(value: CacheResultT, *, cached: bool) -> CacheResultT:
    return cast(CacheResultT, value.model_copy(update={"cached": cached}))


class HiveMetadataCache:
    """Bounded cache whose async loader runs outside its state lock."""

    def __init__(
        self,
        ttl_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            isinstance(ttl_seconds, bool)
            or not math.isfinite(ttl_seconds)
            or ttl_seconds < 0
        ):
            raise ValueError("cache TTL must be a finite non-negative number")
        self._ttl_seconds = float(ttl_seconds)
        self._clock = clock
        self._entries: OrderedDict[HiveCacheKey, _CacheEntry] = OrderedDict()
        self._lock = RLock()

    async def get_or_load(
        self,
        key: HiveCacheKey,
        loader: Callable[[], Awaitable[CacheResultT]],
    ) -> CacheResultT:
        """Return a hit or cache a validated successful loader result."""

        key = _validated_key(key)
        if self._ttl_seconds > 0:
            cached_value = self._get(key)
            if cached_value is not None:
                return _with_cache_status(cast(CacheResultT, cached_value), cached=True)

        loaded = cast(CacheResultT, _validated_result(key, await loader()))
        fresh = _with_cache_status(loaded, cached=False)
        if self._ttl_seconds > 0:
            self._put(key, fresh)
        return fresh

    def _get(self, key: HiveCacheKey) -> CacheableHiveResult | None:
        with self._lock:
            now = self._clock()
            entry = self._entries.get(key)
            if entry is None:
                return None
            if now >= entry.expires_at:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return entry.value

    def _put(self, key: HiveCacheKey, value: CacheableHiveResult) -> None:
        with self._lock:
            now = self._clock()
            expired_keys = [
                existing_key
                for existing_key, entry in self._entries.items()
                if now >= entry.expires_at
            ]
            for expired_key in expired_keys:
                del self._entries[expired_key]

            self._entries[key] = _CacheEntry(
                value=value,
                expires_at=now + self._ttl_seconds,
            )
            self._entries.move_to_end(key)
            while len(self._entries) > MAX_CACHE_ENTRIES:
                self._entries.popitem(last=False)
