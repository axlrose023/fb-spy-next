from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.health import router

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_ping_endpoint_is_owned_by_health_router() -> None:
    app = FastAPI()
    app.include_router(router)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/ping")

    assert response.status_code == 200
    assert response.json() == {"message": "pong"}
