from __future__ import annotations

import pytest

from app.ad_library.ads import AdService
from app.ad_library.ads.adapters.persistence import SqlAlchemyAdRepository
from app.ad_library.ioc import AdLibraryProvider
from app.ad_library.media import MediaService, MediaStorage, MediaURLSigner
from app.ad_library.statistics import StatisticsService
from app.ad_library.statistics.adapters import SqlAlchemyAdStatisticsReader
from app.ioc import get_async_container

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_root_container_resolves_ad_library_graph() -> None:
    assert AdLibraryProvider is not None
    container = get_async_container()
    try:
        async with container() as request:
            dependencies = (
                await request.get(MediaURLSigner),
                await request.get(MediaStorage),
                await request.get(SqlAlchemyAdRepository),
                await request.get(MediaService),
                await request.get(AdService),
                await request.get(SqlAlchemyAdStatisticsReader),
                await request.get(StatisticsService),
            )

            assert all(dependency is not None for dependency in dependencies)
    finally:
        await container.close()
