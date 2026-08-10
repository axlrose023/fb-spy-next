from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

SRC_ROOT = Path(__file__).parents[2]
APP_ROOT = SRC_ROOT / "app"
REMOVED_FACADES = {
    "app.services.facebook": APP_ROOT / "services/facebook/__init__.py",
    "app.services.facebook.calibration": (
        APP_ROOT / "services/facebook/calibration.py"
    ),
    "app.services.facebook.engagement": APP_ROOT / "services/facebook/engagement.py",
    "app.services.facebook.health": APP_ROOT / "services/facebook/health.py",
    "app.services.facebook.importer": APP_ROOT / "services/facebook/importer.py",
    "app.services.facebook.language": APP_ROOT / "services/facebook/language.py",
    "app.services.facebook.landing_archive": (
        APP_ROOT / "services/facebook/landing_archive.py"
    ),
    "app.services.facebook.offer_funnel": (
        APP_ROOT / "services/facebook/offer_funnel.py"
    ),
    "app.services.facebook.runner_process": (
        APP_ROOT / "services/facebook/runner_process.py"
    ),
    "app.services.facebook.relevance": APP_ROOT / "services/facebook/relevance.py",
}


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


def test_removed_facebook_facade_files_do_not_return() -> None:
    assert all(not path.exists() for path in REMOVED_FACADES.values())


def test_production_does_not_import_removed_facebook_facades() -> None:
    violations: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        removed = sorted(_imports(path) & REMOVED_FACADES.keys())
        if removed:
            relative = path.relative_to(APP_ROOT)
            violations.append(f"{relative}: {', '.join(removed)}")

    assert violations == []
