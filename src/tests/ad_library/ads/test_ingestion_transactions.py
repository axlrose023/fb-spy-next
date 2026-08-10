from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.ad_library.ads.adapters.persistence import FacebookAd
from app.ad_library.media import MediaStorage, MediaStorageError
from app.database.uow import UnitOfWork
from app.facebook.runs.adapters import FacebookAdsImporter
from app.facebook.runs.adapters.persistence import FacebookRun
from app.settings import Config, FacebookConfig, MediaStorageConfig

pytestmark = pytest.mark.integration


class FailingMediaStorage:
    backend = "s3"

    async def upload_ads(
        self,
        _ads: list[FacebookAd],
        *,
        relevance_verified: bool,
    ) -> int:
        del relevance_verified
        raise MediaStorageError("simulated upload failure")


def config(data_dir: Path) -> Config:
    return Config(
        media=MediaStorageConfig(
            backend="local",
            signing_secret="test-media-signing-secret-at-least-32-characters",
        ),
        facebook=FacebookConfig(data_dir=data_dir),
    )


async def test_ingestion_transaction_rolls_back_database_on_media_failure(
    tmp_path: Path,
    engine: AsyncEngine,
) -> None:
    run_dir = tmp_path / "rollback-import"
    run_dir.mkdir()
    ads_json = run_dir / "ads.json"
    ads_json.write_text(
        json.dumps(
            [
                {
                    "advertiser": "Rollback Contract Ad",
                    "ad_type": "link",
                    "country": "Rollbackland",
                    "fb_ad_id": "rollback-1",
                }
            ]
        ),
        encoding="utf-8",
    )
    importer = FacebookAdsImporter(
        config(tmp_path),
        media_storage=cast(MediaStorage, FailingMediaStorage()),
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    with pytest.raises(MediaStorageError, match="simulated"):
        async with sessions() as session, UnitOfWork(session) as uow:
            run = FacebookRun(status="completed", title="rollback contract")
            await uow.facebook_runs.create(run)
            await importer.import_ads_json(
                uow,
                run,
                ads_json,
                apply_relevance=False,
            )
            await uow.commit()

    async with sessions() as verification:
        ad_count = await verification.scalar(
            select(func.count())
            .select_from(FacebookAd)
            .where(FacebookAd.advertiser == "Rollback Contract Ad")
        )
        run_count = await verification.scalar(
            select(func.count())
            .select_from(FacebookRun)
            .where(FacebookRun.title == "rollback contract")
        )
    assert ad_count == 0
    assert run_count == 0


async def test_repeated_run_import_is_idempotent_and_preserves_mapped_fields(
    tmp_path: Path,
    uow: UnitOfWork,
) -> None:
    run_dir = tmp_path / "repeat-import"
    media_dir = run_dir / "screens"
    media_dir.mkdir(parents=True)
    (media_dir / "ad.png").write_bytes(b"image")
    ads_json = run_dir / "ads.json"
    ads_json.write_text(
        json.dumps(
            [
                {
                    "advertiser": "Repeat Contract Ad",
                    "ad_type": "link",
                    "screenshot": "screens/ad.png",
                    "fb_ad_id": "repeat-1",
                    "relevance": {"language": "French"},
                }
            ]
        ),
        encoding="utf-8",
    )
    importer = FacebookAdsImporter(config(tmp_path))
    run = FacebookRun(
        status="completed",
        title="repeat contract",
        profile_country="Canada",
    )
    await uow.facebook_runs.create(run)

    await importer.import_ads_json(uow, run, ads_json, apply_relevance=False)
    await importer.import_ads_json(uow, run, ads_json, apply_relevance=False)

    rows = (
        await uow.session.scalars(select(FacebookAd).where(FacebookAd.run_id == run.id))
    ).all()
    assert len(rows) == 1
    assert rows[0].country == "Canada"
    assert rows[0].language == "fr"
    assert rows[0].screenshot_path == "repeat-import/screens/ad.png"
