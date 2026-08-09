from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

import app.facebook.calibration as calibration
from app.facebook.calibration.adapters.persistence import database_targets
from app.services.facebook import calibration as legacy_calibration

pytestmark = pytest.mark.unit

PERSISTENCE_EXPORTS = (
    "append_event",
    "load_engagement_targets_from_ads_json",
    "load_saved_facebook_targets_from_ads_json",
    "load_targets_from_ads_json",
    "load_targets_from_db",
    "quarantined_facebook_post_urls",
    "record_facebook_post_target_result",
    "write_json",
    "write_targets",
)


def test_legacy_calibration_module_preserves_public_object_identity() -> None:
    for name in PERSISTENCE_EXPORTS:
        assert getattr(legacy_calibration, name) is getattr(calibration, name)


def test_json_target_exports_do_not_eagerly_load_database_runtime() -> None:
    source = (
        "import sys; "
        "from app.facebook.calibration import "
        "load_targets_from_ads_json, quarantined_facebook_post_urls; "
        "assert 'app.database.engine' not in sys.modules"
    )

    completed = subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    "source",
    [
        (
            "from app.database.uow import UnitOfWork; "
            "from app.facebook.calibration import load_targets_from_db"
        ),
        (
            "from app.facebook.calibration import load_targets_from_db; "
            "from app.database.uow import UnitOfWork"
        ),
    ],
)
def test_database_uow_and_calibration_loader_are_import_order_independent(
    source: str,
) -> None:
    completed = subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


@pytest.mark.asyncio
async def test_database_loader_maps_rows_without_owning_transactions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = uuid4()
    captured_at = datetime(2026, 8, 9, 12, tzinfo=UTC)
    ad = SimpleNamespace(
        run_id=run_id,
        source_index=7,
        advertiser="Database advertiser",
        displayed_domain="offer.example",
        headline="Database headline",
        ad_text="Database text",
        cta="Learn more",
        country=None,
        fb_ad_id="ad-7",
        landing_full="https://offer.example/full",
        landing_clean="https://offer.example/",
        creative_img=None,
        captured_at=captured_at,
    )
    run = SimpleNamespace(profile_country="Canada")
    statements: list[object] = []

    class Rows:
        def all(self) -> list[tuple[object, object]]:
            return [(ad, run)]

    class Session:
        async def __aenter__(self) -> Session:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def execute(self, statement: object) -> Rows:
            statements.append(statement)
            return Rows()

    monkeypatch.setattr(database_targets, "SessionFactory", Session)
    config = SimpleNamespace(
        facebook=SimpleNamespace(default_country="Spain"),
    )

    targets = await database_targets.load_targets_from_db(
        config,
        country="Canada",
        octo_profile_uuid="profile-7",
        run_id=run_id,
        limit=3,
    )

    assert len(statements) == 1
    assert len(targets) == 1
    assert targets[0].advertiser == "Database advertiser"
    assert targets[0].country == "Canada"
    assert targets[0].source == "db"
    assert targets[0].source_index == 7
