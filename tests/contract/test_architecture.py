from pathlib import Path

import pytest

from tests.contract.import_rules import find_import_violations

SOURCE_ROOT = Path(__file__).parents[2] / "src"


def _write_module(root: Path, relative_path: str, source: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_core_to_plugin_import_is_rejected(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    _write_module(
        source_root,
        "mcp_stdio/core/config.py",
        "from mcp_stdio.plugins.hive import config\n",
    )

    violations = find_import_violations(source_root)

    assert [(item.rule, item.imported) for item in violations] == [
        ("core-to-plugin", "mcp_stdio.plugins.hive"),
    ]


def test_service_to_infrastructure_imports_are_rejected(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    _write_module(
        source_root,
        "mcp_stdio/plugins/hive/service.py",
        "import pyhive\nfrom .pyhive import HiveConnection\n",
    )

    violations = find_import_violations(source_root)

    assert [(item.rule, item.imported) for item in violations] == [
        ("service-to-infrastructure", "pyhive"),
        ("service-to-infrastructure", "mcp_stdio.plugins.hive.pyhive"),
    ]


def test_plugin_to_plugin_import_is_rejected(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    _write_module(
        source_root,
        "mcp_stdio/plugins/hive/tools.py",
        "from ..zeppelin import service\n",
    )

    violations = find_import_violations(source_root)

    assert [(item.rule, item.imported) for item in violations] == [
        ("plugin-to-plugin", "mcp_stdio.plugins.zeppelin"),
    ]


def test_only_registry_may_import_a_concrete_plugin_from_shared_code(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "src"
    _write_module(
        source_root,
        "mcp_stdio/bootstrap.py",
        "from mcp_stdio.plugins.hive import plugin\n",
    )

    violations = find_import_violations(source_root)

    assert [(item.rule, item.imported) for item in violations] == [
        ("shared-to-plugin", "mcp_stdio.plugins.hive"),
    ]


def test_source_tree_respects_architecture_import_boundaries() -> None:
    assert find_import_violations(SOURCE_ROOT) == []


@pytest.mark.parametrize(
    "source, imported",
    [
        ("import websockets\n", "websockets"),
        (
            "from mcp_stdio.plugins.zeppelin import websocket_client\n",
            "mcp_stdio.plugins.zeppelin.websocket_client",
        ),
        ("from websockets.asyncio.client import connect\n", "websockets.asyncio.client"),
        (
            "from .websocket_client import query_bindings\n",
            "mcp_stdio.plugins.zeppelin.websocket_client",
        ),
        (
            "import mcp_stdio.plugins.zeppelin.websocket_client\n",
            "mcp_stdio.plugins.zeppelin.websocket_client",
        ),
    ],
)
def test_service_websocket_imports_are_rejected(tmp_path: Path, source: str, imported: str) -> None:
    root = tmp_path / "src"
    _write_module(root, "mcp_stdio/plugins/zeppelin/service.py", source)
    assert [(v.rule, v.imported) for v in find_import_violations(root)] == [
        ("service-to-infrastructure", imported),
    ]


def test_registry_exemption_does_not_allow_other_shared_zeppelin_imports(tmp_path: Path) -> None:
    root = tmp_path / "src"
    source = "from mcp_stdio.plugins.zeppelin.plugin import PLUGIN_DEFINITION\n"
    _write_module(root, "mcp_stdio/registry.py", source)
    _write_module(root, "mcp_stdio/bootstrap.py", source)
    assert [(v.rule, v.module, v.imported) for v in find_import_violations(root)] == [
        ("shared-to-plugin", "mcp_stdio.bootstrap", "mcp_stdio.plugins.zeppelin.plugin"),
    ]


@pytest.mark.parametrize(
    "source, imported",
    [
        ("from .files import process_archive\n", "mcp_stdio.plugins.spark.files"),
        ("from .cache import SparkEventLogAdapter\n", "mcp_stdio.plugins.spark.cache"),
        ("from mcp_stdio.plugins.spark import cache\n", "mcp_stdio.plugins.spark.cache"),
    ],
)
def test_spark_service_file_adapters_are_rejected(
    tmp_path: Path, source: str, imported: str
) -> None:
    root = tmp_path / "src"
    _write_module(root, "mcp_stdio/plugins/spark/service.py", source)
    assert [(v.rule, v.imported) for v in find_import_violations(root)] == [
        ("service-to-infrastructure", imported),
    ]


@pytest.mark.parametrize("module", ["inspection", "inspection_reader", "inspection_events"])
@pytest.mark.parametrize(
    "form",
    [
        "from .{module} import Value\n",
        "from mcp_stdio.plugins.spark import {module}\n",
        "import mcp_stdio.plugins.spark.{module}\n",
    ],
)
def test_spark_service_inspection_infrastructure_rejected(
    tmp_path: Path, module: str, form: str
) -> None:
    root = tmp_path / "src"
    _write_module(root, "mcp_stdio/plugins/spark/service.py", form.format(module=module))
    assert [(v.rule, v.imported) for v in find_import_violations(root)] == [
        ("service-to-infrastructure", "mcp_stdio.plugins.spark." + module),
    ]
