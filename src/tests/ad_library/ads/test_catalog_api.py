from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.auth.adapters import JwtTokenCodec
from app.accounts.users import UserRole
from app.accounts.users.adapters.persistence import UserRecord
from app.ad_library.ads.adapters.persistence import FacebookAd
from app.facebook.runs.adapters.persistence import FacebookRun
from app.settings import get_config

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(autouse=True)
async def cleanup_catalog_records(session: AsyncSession) -> AsyncIterator[None]:
    yield
    await session.rollback()
    await session.execute(
        delete(FacebookAd).where(FacebookAd.country.in_(("Catalogland", "Searchland")))
    )
    await session.execute(
        delete(FacebookRun).where(FacebookRun.title == "ads catalog contract")
    )
    await session.execute(
        delete(UserRecord).where(UserRecord.username == "ads-catalog-admin")
    )
    await session.commit()


async def auth_headers(session: AsyncSession) -> dict[str, str]:
    user = UserRecord(
        username="ads-catalog-admin",
        password="unused-test-password-hash",
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    config = get_config()
    tokens = JwtTokenCodec(
        secret_key=config.jwt.secret_key,
        algorithm=config.jwt.algorithm,
        access_ttl=timedelta(minutes=config.jwt.access_token_expires_in_minutes),
        refresh_ttl=timedelta(minutes=config.jwt.refresh_expires_in_minutes),
    ).create_pair(user.id)
    return {"Authorization": f"Bearer {tokens.access_token}"}


async def seed_catalog(
    session: AsyncSession,
    *,
    country: str,
) -> list[FacebookAd]:
    run = FacebookRun(status="completed", title="ads catalog contract")
    session.add(run)
    await session.flush()
    captured = datetime(2026, 8, 1, tzinfo=UTC)
    ads = [
        FacebookAd(
            run_id=run.id,
            advertiser="Catalog Alpha",
            ad_type="link",
            format="image",
            country=country,
            language="en",
            landing_full="https://alpha.example/offer",
            screenshot_path="catalog/alpha.png",
            captured_at=captured + timedelta(days=2),
        ),
        FacebookAd(
            run_id=run.id,
            advertiser="Catalog Beta",
            ad_type="video",
            format="video",
            country=country,
            language="es",
            has_video=True,
            video_path="catalog/beta.mp4",
            captured_at=captured + timedelta(days=1),
        ),
        FacebookAd(
            run_id=run.id,
            advertiser="Catalog Gamma",
            ad_type="link",
            format="image",
            country=country,
            language="en",
            captured_at=captured,
        ),
    ]
    session.add_all(ads)
    await session.commit()
    return ads


async def test_catalog_preserves_filters_pagination_order_and_media_proxy(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    headers = await auth_headers(session)
    await seed_catalog(session, country="Catalogland")

    first = await client.get(
        "/ads",
        params={"country": "Catalogland", "page": 1, "page_size": 2},
        headers=headers,
    )

    assert first.status_code == 200
    page = first.json()
    assert page["total"] == 3
    assert [item["advertiser"] for item in page["items"]] == [
        "Catalog Alpha",
        "Catalog Beta",
    ]
    alpha = page["items"][0]
    assert alpha["screenshot_url"].startswith(
        f"/media/ads/{alpha['id']}/screenshot?token="
    )
    assert "screenshot_path" not in alpha

    second = await client.get(
        "/ads",
        params={"country": "Catalogland", "page": 2, "page_size": 2},
        headers=headers,
    )
    assert [item["advertiser"] for item in second.json()["items"]] == ["Catalog Gamma"]

    english = await client.get(
        "/ads",
        params={"country": "Catalogland", "language": "en"},
        headers=headers,
    )
    assert {item["advertiser"] for item in english.json()["items"]} == {
        "Catalog Alpha",
        "Catalog Gamma",
    }

    unresolved = await client.get(
        "/ads",
        params={"country": "Catalogland", "has_landing": False},
        headers=headers,
    )
    assert {item["advertiser"] for item in unresolved.json()["items"]} == {
        "Catalog Beta",
        "Catalog Gamma",
    }


async def test_catalog_preserves_search_multi_type_and_detail_errors(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    headers = await auth_headers(session)
    ads = await seed_catalog(session, country="Searchland")

    response = await client.get(
        "/ads",
        params=[
            ("country", "Searchland"),
            ("q", "Beta"),
            ("ad_type", "link"),
            ("ad_type", "video"),
        ],
        headers=headers,
    )

    assert response.status_code == 200
    assert [item["advertiser"] for item in response.json()["items"]] == ["Catalog Beta"]
    detail = await client.get(f"/ads/{ads[0].id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["advertiser"] == "Catalog Alpha"
    missing = await client.get(
        "/ads/00000000-0000-0000-0000-000000000001",
        headers=headers,
    )
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Ad not found"}
