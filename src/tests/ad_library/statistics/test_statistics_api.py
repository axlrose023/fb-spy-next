from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.accounts.auth.adapters import JwtTokenCodec
from app.accounts.users import UserRole
from app.accounts.users.adapters.persistence import UserRecord
from app.ad_library.ads.adapters.persistence import FacebookAd
from app.ad_library.statistics.adapters import SqlAlchemyAdStatisticsReader
from app.api.modules.runs.models import FacebookRun
from app.settings import get_config

pytestmark = pytest.mark.integration


async def clear_statistics_records(session: AsyncSession) -> None:
    await session.execute(delete(FacebookAd))
    await session.execute(delete(FacebookRun))
    await session.execute(
        delete(UserRecord).where(UserRecord.username == "statistics-admin")
    )
    await session.commit()


@pytest_asyncio.fixture(autouse=True)
async def isolated_statistics_data(
    session: AsyncSession,
) -> AsyncIterator[None]:
    await clear_statistics_records(session)
    yield
    await session.rollback()
    await clear_statistics_records(session)


async def auth_headers(session: AsyncSession) -> dict[str, str]:
    user = UserRecord(
        username="statistics-admin",
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


async def seed_ads(session: AsyncSession) -> None:
    run = FacebookRun(status="completed", title="statistics contract")
    session.add(run)
    await session.flush()
    session.add_all(
        [
            FacebookAd(
                run_id=run.id,
                advertiser="Alpha",
                ad_type="link",
                format="image",
                vertical="finance",
                country="Statsland",
                language="en",
                platform="facebook",
                placement="feed",
                displayed_domain="shared.example",
                cta="Learn More",
                landing_full="https://shared.example/one",
                screenshot_ok=False,
            ),
            FacebookAd(
                run_id=run.id,
                advertiser="Alpha",
                ad_type="link",
                format="video",
                vertical="finance",
                country="Statsland",
                language="en",
                platform="facebook",
                placement="feed",
                displayed_domain="shared.example",
                cta="Learn More",
                has_video=True,
                screenshot_ok=True,
            ),
            FacebookAd(
                run_id=run.id,
                advertiser="",
                ad_type="video",
                format="image",
                vertical=None,
                country=None,
                language=None,
                platform="facebook",
                placement="story",
                displayed_domain="",
                cta="",
                has_video=True,
                landing_full="https://video.example/offer",
                screenshot_ok=None,
            ),
            FacebookAd(
                run_id=run.id,
                advertiser="Beta",
                ad_type="carousel",
                format="image",
                vertical="gaming",
                country="Otherland",
                language="es",
                platform="instagram",
                placement="feed",
                displayed_domain="other.example",
                cta="Shop Now",
                screenshot_ok=False,
            ),
        ]
    )
    await session.commit()


async def test_empty_statistics_response_keeps_public_schema(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    response = await client.get(
        "/stats/ads",
        headers=await auth_headers(session),
    )

    assert response.status_code == 200
    assert response.json() == {
        "total_ads": 0,
        "link_ads": 0,
        "resolved_ads": 0,
        "video_ads": 0,
        "bad_screenshots": 0,
        "by_type": [],
        "by_format": [],
        "by_vertical": [],
        "by_country": [],
        "by_language": [],
        "by_platform": [],
        "by_placement": [],
        "by_domain": [],
        "by_advertiser": [],
        "by_cta": [],
    }


async def test_statistics_preserve_counts_facets_and_empty_value_handling(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    headers = await auth_headers(session)
    await seed_ads(session)

    response = await client.get("/stats/ads", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert {
        key: payload[key]
        for key in (
            "total_ads",
            "link_ads",
            "resolved_ads",
            "video_ads",
            "bad_screenshots",
        )
    } == {
        "total_ads": 4,
        "link_ads": 2,
        "resolved_ads": 2,
        "video_ads": 2,
        "bad_screenshots": 2,
    }
    assert payload["by_country"] == [
        {"value": "Statsland", "count": 2},
        {"value": "Otherland", "count": 1},
    ]
    assert payload["by_language"] == [
        {"value": "en", "count": 2},
        {"value": "es", "count": 1},
    ]
    assert payload["by_domain"] == [
        {"value": "shared.example", "count": 2},
        {"value": "other.example", "count": 1},
    ]
    assert payload["by_advertiser"] == [
        {"value": "Alpha", "count": 2},
        {"value": "Beta", "count": 1},
    ]
    assert payload["by_vertical"] == [
        {"value": "finance", "count": 2},
        {"value": "gaming", "count": 1},
    ]
    assert all(item["value"] not in (None, "") for item in payload["by_cta"])


async def test_statistics_reader_uses_two_selects_for_all_aggregates(
    engine: AsyncEngine,
    session: AsyncSession,
) -> None:
    await seed_ads(session)
    selects: list[str] = []

    def record_select(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record_select)
    try:
        result = await SqlAlchemyAdStatisticsReader(
            session,
            FacebookAd,
        ).read_ads_statistics(facet_limit=30)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record_select)

    assert result.total_ads == 4
    assert len(selects) == 2
