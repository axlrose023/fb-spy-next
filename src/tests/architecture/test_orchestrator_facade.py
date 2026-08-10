from __future__ import annotations

import subprocess
import sys

import pytest

pytestmark = pytest.mark.architecture

LEGACY_MODULE = "app.services.facebook_orchestrator"
CANONICAL_MODULE = "app.facebook.orchestration.runtime"


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
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert completed.returncode == 0, completed.stderr
