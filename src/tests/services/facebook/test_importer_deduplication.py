import json

from sqlalchemy import select

from app.api.modules.ads.models import FacebookAd
from app.api.modules.runs.models import FacebookRun
from app.facebook.runs.adapters import FacebookAdsImporter
from app.settings import Config, FacebookConfig, MediaStorageConfig


async def test_importer_deduplicates_exact_ad_per_geo_but_keeps_distinct_ads(
    tmp_path,
    uow,
) -> None:
    config = Config(
        media=MediaStorageConfig(
            backend="local",
            signing_secret="test-media-signing-secret-at-least-32-characters",
        ),
        facebook=FacebookConfig(data_dir=tmp_path),
    )
    importer = FacebookAdsImporter(config)

    async def import_ads(
        run_name: str,
        country: str,
        fb_ad_ids: list[str],
    ) -> FacebookRun:
        run_dir = tmp_path / run_name
        run_dir.mkdir()
        ads_json = run_dir / "ads.json"
        ads_json.write_text(
            json.dumps(
                [
                    {
                        "advertiser": "Same Creative",
                        "ad_type": "link",
                        "displayed_domain": "duplicate.test",
                        "headline": "Same headline",
                        "ad_text": "Same text",
                        "cta": "Learn More",
                        "fb_ad_id": fb_ad_id,
                        "country": country,
                    }
                    for fb_ad_id in fb_ad_ids
                ]
            ),
            encoding="utf-8",
        )
        run = FacebookRun(
            status="completed",
            title=run_name,
            profile_country=country,
        )
        await uow.facebook_runs.create(run)
        await importer.import_ads_json(
            uow,
            run,
            ads_json,
            apply_relevance=False,
        )
        return run

    first = await import_ads("spain-first", " Spain ", ["same-id", "same-id"])
    repeated = await import_ads("spain-repeated", "Spain", ["same-id"])
    other_geo = await import_ads("canada-same-id", "Canada", ["same-id"])
    distinct_ad = await import_ads("spain-other-id", "Spain", ["other-id"])
    await uow.commit()

    rows = (
        (
            await uow.session.execute(
                select(FacebookAd).where(FacebookAd.advertiser == "Same Creative")
            )
        )
        .scalars()
        .all()
    )

    assert first.total_ads == 2
    assert repeated.total_ads == 1
    assert other_geo.total_ads == 1
    assert distinct_ad.total_ads == 1
    assert sorted((row.country, row.fb_ad_id) for row in rows) == [
        ("Canada", "same-id"),
        ("Spain", "other-id"),
        ("Spain", "same-id"),
    ]
