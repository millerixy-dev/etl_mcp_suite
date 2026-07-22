from pathlib import Path

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


def test_source_tree_respects_architecture_import_boundaries() -> None:
    assert find_import_violations(SOURCE_ROOT) == []
