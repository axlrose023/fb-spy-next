from __future__ import annotations

import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "source",
    [
        (
            "from app.database.uow import UnitOfWork; "
            "from app.facebook.runs.adapters import FacebookAdsImporter"
        ),
        (
            "from app.facebook.runs.adapters import FacebookAdsImporter; "
            "from app.database.uow import UnitOfWork"
        ),
    ],
)
def test_uow_and_importer_are_import_order_independent(source: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
