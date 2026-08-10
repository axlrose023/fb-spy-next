from __future__ import annotations

import ast
from pathlib import Path

import pytest

from .legacy_inventory import FORBIDDEN_IMPORT_PREFIXES, REMOVED_MODULES

pytestmark = pytest.mark.architecture

APP_ROOT = Path(__file__).parents[2] / "app"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_removed_legacy_module_files_do_not_return() -> None:
    assert all(not path.exists() for path in REMOVED_MODULES.values())


def test_production_does_not_import_removed_legacy_modules() -> None:
    violations: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        removed = sorted(
            module
            for module in _imports(path)
            if any(
                module == prefix or module.startswith(f"{prefix}.")
                for prefix in FORBIDDEN_IMPORT_PREFIXES
            )
        )
        if removed:
            relative = path.relative_to(APP_ROOT)
            violations.append(f"{relative}: {', '.join(removed)}")

    assert violations == []
