"""Opt-in, read-only HiveServer2 integration coverage."""

from __future__ import annotations

import json
import os

import pytest

from mcp_stdio.core.errors import ErrorCategory
from mcp_stdio.plugins.hive.cache import HiveMetadataCache
from mcp_stdio.plugins.hive.config import HiveSecrets, HiveSettings
from mcp_stdio.plugins.hive.gateway import HiveGatewayError
from mcp_stdio.plugins.hive.pyhive import PyHiveMetadataAdapter
from mcp_stdio.plugins.hive.service import HiveSchemaService

_OPT_IN_VARIABLE = "MCP_STDIO_HIVE_INTEGRATION"
_REQUIRED_VARIABLES = (
    "MCP_STDIO_HIVE_HOST",
    "MCP_STDIO_HIVE_PORT",
    "MCP_STDIO_HIVE_DATABASE",
    "MCP_STDIO_HIVE_TABLE",
    "MCP_STDIO_HIVE_USERNAME",
    "MCP_STDIO_HIVE_PASSWORD",
)
_MISSING_TABLE_PREFIX = "mcp_stdio_integration_missing_table_8e31c7a29f4d46b0"


def _integration_environment() -> dict[str, str]:
    if os.environ.get(_OPT_IN_VARIABLE) != "1":
        pytest.skip(f"set {_OPT_IN_VARIABLE}=1 to opt in to live HiveServer2 testing")

    values: dict[str, str] = {}
    missing: list[str] = []
    for variable_name in _REQUIRED_VARIABLES:
        value = os.environ.get(variable_name)
        if value is None or not value:
            missing.append(variable_name)
        else:
            values[variable_name] = value
    if missing:
        pytest.skip("missing required Hive integration variables: " + ", ".join(missing))
    return values


def _strict_port(value: str) -> int:
    if not value.isascii() or not value.isdecimal():
        pytest.fail("MCP_STDIO_HIVE_PORT must be an ASCII decimal integer")
    return int(value)


def _known_missing_table(existing_tables: tuple[str, ...]) -> str:
    normalized_tables = {table.casefold() for table in existing_tables}
    for suffix in range(256):
        candidate = f"{_MISSING_TABLE_PREFIX}_{suffix}"
        if candidate.casefold() not in normalized_tables:
            return candidate
    pytest.fail("could not select a guaranteed-absent Hive integration table")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_hiveserver2_metadata_and_safe_failure() -> None:
    environment = _integration_environment()
    username = environment["MCP_STDIO_HIVE_USERNAME"]
    password = environment["MCP_STDIO_HIVE_PASSWORD"]
    settings = HiveSettings(
        host=environment["MCP_STDIO_HIVE_HOST"],
        port=_strict_port(environment["MCP_STDIO_HIVE_PORT"]),
        database=environment["MCP_STDIO_HIVE_DATABASE"],
        cache_ttl_seconds=0,
    )
    secrets = HiveSecrets(username=username, password=password)
    service = HiveSchemaService(
        gateway=PyHiveMetadataAdapter(settings=settings, secrets=secrets),
        cache=HiveMetadataCache(settings.cache_ttl_seconds),
    )
    table = environment["MCP_STDIO_HIVE_TABLE"]

    databases = await service.list_databases()
    assert settings.database.casefold() in {
        database.casefold() for database in databases.databases
    }
    assert databases.cached is False

    tables = await service.list_tables(settings.database)
    assert table.casefold() in {table_name.casefold() for table_name in tables.tables}
    assert tables.cached is False
    missing_table = _known_missing_table(tables.tables)

    schema = await service.get_table_schema(
        settings.database,
        table,
        include_ddl=True,
    )
    assert schema.columns
    assert schema.partition_columns, (
        "MCP_STDIO_HIVE_TABLE must name a table with at least one partition column"
    )
    assert schema.ddl is not None and schema.ddl.strip()
    assert schema.cached is False

    with pytest.raises(HiveGatewayError) as captured:
        await service.get_table_schema(
            settings.database,
            missing_table,
            include_ddl=False,
        )

    error = captured.value
    assert error.tool_error.category in {
        ErrorCategory.NOT_FOUND,
        ErrorCategory.UPSTREAM_ERROR,
    }
    serialized = json.dumps(
        error.tool_error.to_dict(secret_values=(username, password)),
        sort_keys=True,
    )
    for safe_view in (str(error), repr(error), serialized):
        assert username not in safe_view
        assert password not in safe_view
