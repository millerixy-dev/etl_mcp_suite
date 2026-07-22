"""Hive metadata TTL/LRU cache tests."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from queue import Queue
from threading import Event, Lock, Thread
from typing import cast

import pytest

from mcp_stdio.plugins.hive.cache import (
    HiveCacheKey,
    HiveMetadataCache,
    make_hive_cache_key,
)
from mcp_stdio.plugins.hive.models import (
    ListDatabasesResult,
    ListTablesResult,
    TableSchemaResult,
)


class FakeClock:
    """Controllable monotonic clock for deterministic expiry tests."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class CredentialBearingResult(ListDatabasesResult):
    """Malicious subtype that must not cross the exact cache value boundary."""

    credential: str


class GateLock:
    """Test lock that blocks one selected entry until the test releases it."""

    def __init__(self, *, block_on_enter: int) -> None:
        self._block_on_enter = block_on_enter
        self._enter_count = 0
        self._count_lock = Lock()
        self.blocked = Event()
        self.release = Event()

    def __enter__(self) -> None:
        with self._count_lock:
            self._enter_count += 1
            should_block = self._enter_count == self._block_on_enter
        if should_block:
            self.blocked.set()
            if not self.release.wait(timeout=2):
                raise TimeoutError("test gate was not released")

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        del exc_type, exc_value, traceback


def database_result(name: str) -> ListDatabasesResult:
    return ListDatabasesResult(databases=(name,), cached=False)


def counting_loader(
    calls: list[str], name: str
) -> Callable[[], Awaitable[ListDatabasesResult]]:
    async def load() -> ListDatabasesResult:
        calls.append(name)
        return database_result(name)

    return load


def counting_tables_loader(
    calls: list[str], database: str, *, label: str | None = None
) -> Callable[[], Awaitable[ListTablesResult]]:
    async def load() -> ListTablesResult:
        calls.append(label or database)
        return ListTablesResult(database=database, tables=("events",), cached=False)

    return load


def threaded_cache_call(
    cache: HiveMetadataCache,
    key: HiveCacheKey,
    loader: Callable[[], Awaitable[ListDatabasesResult]],
) -> tuple[Thread, Queue[object]]:
    outcomes: Queue[object] = Queue()

    def run() -> None:
        try:
            outcomes.put(asyncio.run(cache.get_or_load(key, loader)))
        except BaseException as error:
            outcomes.put(error)

    thread = Thread(target=run, daemon=True)
    thread.start()
    return thread, outcomes


async def test_identical_successful_request_hits_cache_with_accurate_flag() -> None:
    calls: list[str] = []
    cache = HiveMetadataCache(ttl_seconds=30)
    key = make_hive_cache_key("list_databases")

    first = await cache.get_or_load(key, counting_loader(calls, "default"))
    second = await cache.get_or_load(key, counting_loader(calls, "ignored"))

    assert first == database_result("default")
    assert first.cached is False
    assert second.databases == ("default",)
    assert second.cached is True
    assert calls == ["default"]


async def test_elapsed_ttl_removes_entry_and_reloads() -> None:
    calls: list[str] = []
    clock = FakeClock()
    cache = HiveMetadataCache(ttl_seconds=5, clock=clock)
    key = make_hive_cache_key("list_databases")

    await cache.get_or_load(key, counting_loader(calls, "before"))
    clock.advance(5)
    result = await cache.get_or_load(key, counting_loader(calls, "after"))

    assert result == database_result("after")
    assert result.cached is False
    assert calls == ["before", "after"]


async def test_zero_ttl_disables_lookup_and_storage() -> None:
    calls: list[str] = []
    cache = HiveMetadataCache(ttl_seconds=0)
    key = make_hive_cache_key("list_databases")

    first = await cache.get_or_load(key, counting_loader(calls, "first"))
    second = await cache.get_or_load(key, counting_loader(calls, "second"))

    assert first == database_result("first")
    assert second == database_result("second")
    assert first.cached is second.cached is False
    assert calls == ["first", "second"]


def test_cache_keys_normalize_identifiers_and_canonical_arguments() -> None:
    mixed_case = make_hive_cache_key(
        "get_table_schema",
        database="Analytics",
        table="Daily_Events",
        include_ddl=False,
    )
    normalized = make_hive_cache_key(
        "get_table_schema",
        database="analytics",
        table="daily_events",
    )

    assert mixed_case == normalized
    assert make_hive_cache_key("list_tables", database="Analytics") == (
        "list_tables",
        "analytics",
    )
    assert make_hive_cache_key(
        "get_table_schema",
        database="analytics",
        table="daily_events",
        include_ddl=True,
    ) != normalized


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("unknown", {}),
        ("list_databases", {"database": "default"}),
        ("list_tables", {}),
        ("list_tables", {"database": "unsafe.name"}),
        ("get_table_schema", {"database": "default"}),
        (
            "get_table_schema",
            {"database": "default", "table": "events", "include_ddl": 1},
        ),
    ],
)
def test_cache_key_rejects_unknown_or_noncanonical_arguments(
    tool_name: str, arguments: dict[str, object]
) -> None:
    with pytest.raises((TypeError, ValueError)):
        make_hive_cache_key(tool_name, **arguments)  # type: ignore[arg-type]


async def test_loader_failure_is_not_stored() -> None:
    calls = 0
    cache = HiveMetadataCache(ttl_seconds=30)
    key = make_hive_cache_key("list_databases")

    async def fail() -> ListDatabasesResult:
        nonlocal calls
        calls += 1
        raise RuntimeError("upstream failed")

    with pytest.raises(RuntimeError, match="upstream failed"):
        await cache.get_or_load(key, fail)

    result = await cache.get_or_load(key, counting_loader([], "recovered"))

    assert result == database_result("recovered")
    assert result.cached is False
    assert calls == 1


async def test_cache_rejects_non_result_values_without_storing_them() -> None:
    calls = 0
    cache = HiveMetadataCache(ttl_seconds=30)
    key = make_hive_cache_key("list_databases")

    async def invalid_loader() -> object:
        nonlocal calls
        calls += 1
        return object()

    with pytest.raises(TypeError, match="validated Hive metadata result"):
        await cache.get_or_load(key, invalid_loader)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="validated Hive metadata result"):
        await cache.get_or_load(key, invalid_loader)  # type: ignore[arg-type]

    assert calls == 2


async def test_cache_rejects_result_subclasses_with_extra_fields_without_storing() -> None:
    calls = 0
    cache = HiveMetadataCache(ttl_seconds=30)
    key = make_hive_cache_key("list_databases")

    async def load() -> ListDatabasesResult:
        nonlocal calls
        calls += 1
        return CredentialBearingResult(
            databases=("default",),
            cached=False,
            credential="credential-sentinel",
        )

    with pytest.raises(TypeError, match="exact Hive metadata result type"):
        await cache.get_or_load(key, load)
    with pytest.raises(TypeError, match="exact Hive metadata result type"):
        await cache.get_or_load(key, load)

    assert calls == 2


async def test_cache_rejects_noncanonical_direct_key_before_loading() -> None:
    calls: list[str] = []
    cache = HiveMetadataCache(ttl_seconds=30)
    unsafe_key = cast(HiveCacheKey, ("list_tables", "unsafe.name"))

    with pytest.raises(ValueError, match="canonical Hive cache key"):
        await cache.get_or_load(unsafe_key, counting_loader(calls, "not-loaded"))

    assert calls == []


async def test_cache_rejects_result_model_for_another_tool_without_storing() -> None:
    calls = 0
    cache = HiveMetadataCache(ttl_seconds=30)
    key = make_hive_cache_key("list_databases")

    async def wrong_result() -> ListTablesResult:
        nonlocal calls
        calls += 1
        return ListTablesResult(database="default", tables=("events",), cached=False)

    with pytest.raises(TypeError, match="does not match Hive cache key"):
        await cache.get_or_load(key, wrong_result)
    with pytest.raises(TypeError, match="does not match Hive cache key"):
        await cache.get_or_load(key, wrong_result)

    assert calls == 2


@pytest.mark.parametrize(
    ("key", "result"),
    [
        (
            make_hive_cache_key("list_tables", database="analytics"),
            ListTablesResult(database="other", tables=("events",), cached=False),
        ),
        (
            make_hive_cache_key(
                "get_table_schema", database="analytics", table="events"
            ),
            TableSchemaResult(
                database="other",
                table="events",
                columns=(),
                partition_columns=(),
                cached=False,
            ),
        ),
        (
            make_hive_cache_key(
                "get_table_schema", database="analytics", table="events"
            ),
            TableSchemaResult(
                database="analytics",
                table="other",
                columns=(),
                partition_columns=(),
                cached=False,
            ),
        ),
        (
            make_hive_cache_key(
                "get_table_schema",
                database="analytics",
                table="events",
                include_ddl=True,
            ),
            TableSchemaResult(
                database="analytics",
                table="events",
                columns=(),
                partition_columns=(),
                ddl=None,
                cached=False,
            ),
        ),
        (
            make_hive_cache_key(
                "get_table_schema", database="analytics", table="events"
            ),
            TableSchemaResult(
                database="analytics",
                table="events",
                columns=(),
                partition_columns=(),
                ddl="CREATE TABLE `analytics`.`events` (id int)",
                cached=False,
            ),
        ),
    ],
)
async def test_cache_rejects_result_content_mismatched_with_key_without_storing(
    key: HiveCacheKey,
    result: ListTablesResult | TableSchemaResult,
) -> None:
    calls = 0
    cache = HiveMetadataCache(ttl_seconds=30)

    async def load() -> ListTablesResult | TableSchemaResult:
        nonlocal calls
        calls += 1
        return result

    with pytest.raises(TypeError, match="does not match Hive cache key"):
        await cache.get_or_load(key, load)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="does not match Hive cache key"):
        await cache.get_or_load(key, load)  # type: ignore[arg-type]

    assert calls == 2


async def test_cache_accepts_case_normalized_result_identifiers() -> None:
    cache = HiveMetadataCache(ttl_seconds=30)
    key = make_hive_cache_key("list_tables", database="analytics")

    async def load() -> ListTablesResult:
        return ListTablesResult(database="Analytics", tables=("events",), cached=False)

    first = await cache.get_or_load(key, load)
    second = await cache.get_or_load(key, load)

    assert first.cached is False
    assert second.cached is True


def test_get_reads_clock_after_lock_acquisition_at_ttl_boundary() -> None:
    calls: list[str] = []
    clock = FakeClock()
    cache = HiveMetadataCache(ttl_seconds=5, clock=clock)
    key = make_hive_cache_key("list_databases")
    asyncio.run(cache.get_or_load(key, counting_loader(calls, "seed")))
    gate = GateLock(block_on_enter=1)
    vars(cache)["_lock"] = gate

    thread, outcomes = threaded_cache_call(
        cache, key, counting_loader(calls, "reloaded")
    )
    try:
        assert gate.blocked.wait(timeout=2)
        clock.advance(5)
    finally:
        gate.release.set()
        thread.join(timeout=2)

    assert not thread.is_alive()
    result = outcomes.get_nowait()
    assert isinstance(result, ListDatabasesResult)
    assert result == database_result("reloaded")
    assert result.cached is False
    assert calls == ["seed", "reloaded"]


def test_put_reads_clock_after_lock_acquisition_at_ttl_boundary() -> None:
    calls: list[str] = []
    clock = FakeClock()
    cache = HiveMetadataCache(ttl_seconds=5, clock=clock)
    key = make_hive_cache_key("list_databases")
    gate = GateLock(block_on_enter=2)
    vars(cache)["_lock"] = gate

    thread, outcomes = threaded_cache_call(
        cache, key, counting_loader(calls, "seed")
    )
    try:
        assert gate.blocked.wait(timeout=2)
        clock.advance(5)
    finally:
        gate.release.set()
        thread.join(timeout=2)

    assert not thread.is_alive()
    first = outcomes.get_nowait()
    assert isinstance(first, ListDatabasesResult)
    second = asyncio.run(
        cache.get_or_load(key, counting_loader(calls, "not-loaded"))
    )
    assert first.cached is False
    assert second.cached is True
    assert calls == ["seed"]


async def test_cache_evicts_least_recently_used_entry_at_fixed_256_bound() -> None:
    cache = HiveMetadataCache(ttl_seconds=30)
    loader_calls: list[str] = []

    for index in range(256):
        key = make_hive_cache_key("list_tables", database=f"db_{index}")
        await cache.get_or_load(
            key, counting_tables_loader(loader_calls, f"db_{index}")
        )

    most_recent_key = make_hive_cache_key("list_tables", database="db_0")
    refreshed = await cache.get_or_load(
        most_recent_key,
        counting_tables_loader(loader_calls, "db_0", label="not-loaded"),
    )
    await cache.get_or_load(
        make_hive_cache_key("list_tables", database="db_256"),
        counting_tables_loader(loader_calls, "db_256"),
    )
    evicted = await cache.get_or_load(
        make_hive_cache_key("list_tables", database="db_1"),
        counting_tables_loader(loader_calls, "db_1", label="db_1-reloaded"),
    )

    assert refreshed.cached is True
    assert evicted == ListTablesResult(
        database="db_1", tables=("events",), cached=False
    )
    assert evicted.cached is False
    assert "not-loaded" not in loader_calls


async def test_cache_accepts_each_immutable_hive_result_type() -> None:
    cache = HiveMetadataCache(ttl_seconds=30)
    key = make_hive_cache_key("list_tables", database="default")

    async def load() -> ListTablesResult:
        return ListTablesResult(database="default", tables=("events",), cached=False)

    first = await cache.get_or_load(key, load)
    second = await cache.get_or_load(key, load)

    assert first.cached is False
    assert second.cached is True
    assert second.tables == ("events",)
