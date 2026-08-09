from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

SRC_ROOT = Path(__file__).parents[2]
APP_ROOT = SRC_ROOT / "app"
NEW_APPLICATIONS = ("accounts", "ad_library", "facebook", "observability")

INNER_FILES = {
    "contracts.py",
    "exceptions.py",
    "models.py",
    "policies.py",
    "service.py",
}
OUTER_DEPENDENCIES = {
    "alembic",
    "asyncpg",
    "boto3",
    "botocore",
    "dishka",
    "fastapi",
    "google",
    "httpx",
    "jwt",
    "playwright",
    "pydantic",
    "redis",
    "sqlalchemy",
    "subprocess",
    "taskiq",
}
OUTER_APP_MODULES = {
    "app.api",
    "app.application",
    "app.clients",
    "app.database",
    "app.ioc",
    "app.services",
    "app.settings",
    "app.tasks",
    "app.tiq",
    "app.worker",
}
GENERIC_NAMES = {"common", "helpers", "services", "shared", "utils"}


def _new_python_files() -> Iterable[Path]:
    for application in NEW_APPLICATIONS:
        root = APP_ROOT / application
        if root.exists():
            yield from sorted(root.rglob("*.py"))


def _module_name(path: Path) -> str:
    relative = path.relative_to(SRC_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_import(path: Path, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    package = _module_name(path).split(".")
    if path.name != "__init__.py":
        package.pop()
    keep = len(package) - node.level + 1
    base = package[: max(keep, 0)]
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add(_resolve_import(path, node))
    return modules


def _owner(module: str) -> tuple[str, str] | None:
    parts = module.split(".")
    if len(parts) < 3 or parts[0] != "app" or parts[1] not in NEW_APPLICATIONS:
        return None
    return parts[1], parts[2]


def test_new_modules_do_not_use_generic_dumping_ground_names() -> None:
    violations: list[str] = []
    for path in _new_python_files():
        relative = path.relative_to(APP_ROOT)
        names = set(relative.parts[:-1]) | {path.stem}
        if blocked := sorted(names & GENERIC_NAMES):
            violations.append(f"{relative}: {', '.join(blocked)}")
    assert not violations, "Generic module names are forbidden:\n" + "\n".join(
        violations
    )


def test_inner_layers_do_not_import_frameworks_or_adapters() -> None:
    violations: list[str] = []
    for path in _new_python_files():
        relative = path.relative_to(APP_ROOT)
        if path.name not in INNER_FILES or "adapters" in relative.parts:
            continue
        for imported in _imports(path):
            root = imported.partition(".")[0]
            app_module = ".".join(imported.split(".")[:2])
            if (
                root in OUTER_DEPENDENCIES
                or app_module in OUTER_APP_MODULES
                or ".adapters" in imported
            ):
                violations.append(f"{relative} -> {imported}")
    assert not violations, "Inner layer imports outer details:\n" + "\n".join(
        violations
    )


def test_cross_module_imports_use_public_package_api() -> None:
    violations: list[str] = []
    for path in _new_python_files():
        source = _module_name(path)
        source_owner = _owner(source)
        for imported in _imports(path):
            target_owner = _owner(imported)
            if target_owner is None or target_owner == source_owner:
                continue
            if (
                source.endswith(".ioc")
                and source_owner is not None
                and source_owner[0] == target_owner[0]
            ):
                continue
            if len(imported.split(".")) > 3:
                violations.append(f"{source} -> {imported}")
    assert not violations, "Import another module through __init__.py:\n" + "\n".join(
        violations
    )
