from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

SRC_ROOT = Path(__file__).parents[2]
APP_ROOT = SRC_ROOT / "app"
PROJECT_ROOT = SRC_ROOT.parent
LEGACY_MODULE = "app.services.facebook_orchestrator"
LEGACY_PATH = APP_ROOT / "services" / "facebook_orchestrator.py"
CANONICAL_MODULE = "app.facebook.orchestration.runtime"


def _legacy_references(path: Path) -> tuple[bool, bool]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    direct_import = False
    dynamic_reference = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            direct_import |= any(alias.name == LEGACY_MODULE for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            direct_import |= node.module == LEGACY_MODULE
        elif isinstance(node, ast.Constant):
            dynamic_reference |= node.value == LEGACY_MODULE
    return direct_import, dynamic_reference


def test_legacy_orchestrator_has_no_production_consumers() -> None:
    direct_consumers: list[Path] = []
    dynamic_consumers: list[Path] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        if path == LEGACY_PATH:
            continue
        direct, dynamic = _legacy_references(path)
        if direct:
            direct_consumers.append(path.relative_to(APP_ROOT))
        if dynamic:
            dynamic_consumers.append(path.relative_to(APP_ROOT))

    assert direct_consumers == []
    assert dynamic_consumers == []


def test_facebook_gateway_uses_canonical_orchestrator() -> None:
    from app.facebook.commands import COMMANDS

    command = next(item for item in COMMANDS if item.name == "orchestrate")

    assert command.module == CANONICAL_MODULE


def test_canonical_facebook_apis_import_without_legacy_orchestrator() -> None:
    modules = (
        "app.facebook.commands",
        "app.facebook.orchestration",
        "app.facebook.orchestration.adapters",
        "app.facebook.orchestration.commands",
        "app.facebook.orchestration.runtime",
        "app.facebook.calibration",
        "app.facebook.profiles",
    )
    imports = "; ".join(f"import {module}" for module in modules)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import sys; {imports}; assert {LEGACY_MODULE!r} not in sys.modules",
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert completed.returncode == 0, completed.stderr
