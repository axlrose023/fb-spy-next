from __future__ import annotations

import pytest

from app.facebook.ioc import FacebookProvider
from app.facebook.runs import RunService
from app.facebook.runs.adapters import FacebookAdsImporter
from app.facebook.runs.adapters.processes import FacebookRunnerRegistry
from app.ioc import get_async_container

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_root_container_resolves_facebook_graph() -> None:
    assert FacebookProvider is not None
    container = get_async_container()
    try:
        importer = await container.get(FacebookAdsImporter)
        runner_registry = await container.get(FacebookRunnerRegistry)
        assert await container.get(FacebookAdsImporter) is importer
        assert await container.get(FacebookRunnerRegistry) is runner_registry

        async with container() as request:
            assert isinstance(await request.get(RunService), RunService)
    finally:
        await container.close()
