"""AST-based import boundary checks for the modular monolith."""

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ImportViolation:
    rule: str
    module: str
    imported: str
    path: Path
    line: int


def _module_name(source_root: Path, path: Path) -> tuple[str, str]:
    parts = list(path.relative_to(source_root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
        package_parts = parts
    else:
        package_parts = parts[:-1]
    return ".".join(parts), ".".join(package_parts)


def _resolve_from_import(node: ast.ImportFrom, package: str) -> list[str]:
    if node.level == 0:
        return [node.module] if node.module else []

    package_parts = package.split(".") if package else []
    retained_count = max(0, len(package_parts) - (node.level - 1))
    base_parts = package_parts[:retained_count]
    if node.module:
        return [".".join([*base_parts, node.module])]
    return [".".join([*base_parts, alias.name]) for alias in node.names]


def _imports(tree: ast.AST, package: str) -> list[tuple[str, int]]:
    imports: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.extend(
                (imported, node.lineno) for imported in _resolve_from_import(node, package)
            )
    return imports


def _plugin_name(module: str) -> str | None:
    parts = module.split(".")
    if len(parts) >= 3 and parts[:2] == ["mcp_stdio", "plugins"]:
        return parts[2]
    return None


def _is_service_infrastructure_import(module: str, imported: str) -> bool:
    if not module.endswith(".service"):
        return False
    if imported.split(".", maxsplit=1)[0] in {"httpx", "mcp", "pyhive"}:
        return True
    infrastructure_modules = {"http_client", "plugin", "pyhive", "tools"}
    return imported.split(".")[-1] in infrastructure_modules


def find_import_violations(source_root: Path) -> list[ImportViolation]:
    violations: list[ImportViolation] = []
    for path in sorted(source_root.rglob("*.py")):
        module, package = _module_name(source_root, path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported, line in _imports(tree, package):
            rule: str | None = None
            if module.startswith("mcp_stdio.core") and imported.startswith(
                "mcp_stdio.plugins"
            ):
                rule = "core-to-plugin"
            elif _is_service_infrastructure_import(module, imported):
                rule = "service-to-infrastructure"
            else:
                source_plugin = _plugin_name(module)
                imported_plugin = _plugin_name(imported)
                if source_plugin and imported_plugin and source_plugin != imported_plugin:
                    rule = "plugin-to-plugin"

            if rule:
                violations.append(
                    ImportViolation(
                        rule=rule,
                        module=module,
                        imported=imported,
                        path=path,
                        line=line,
                    )
                )
    return violations
