from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.ad_library.ads import Ad, AdNotFoundError, AdPage, AdQuery, AdService
from app.ad_library.ads.catalog import normalize_order
from app.ad_library.media import MediaKind

pytestmark = pytest.mark.unit


class StubCatalog:
    def __init__(self, ads: list[Ad]) -> None:
        self.ads = ads
        self.queries: list[AdQuery] = []

    async def page(self, query: AdQuery) -> AdPage:
        self.queries.append(query)
        return AdPage(self.ads, len(self.ads), query.page, query.page_size)

    async def get(self, ad_id: UUID) -> Ad | None:
        return next((ad for ad in self.ads if ad.id == ad_id), None)


class StubMediaLinks:
    def url_for(
        self,
        ad_id: UUID,
        kind: MediaKind,
        stored_reference: str | None,
        *,
        now: int | None = None,
    ) -> str | None:
        del now
        return f"/proxy/{ad_id}/{kind.value}" if stored_reference else None


def ad() -> Ad:
    now = datetime.now(UTC)
    return Ad(
        id=uuid4(),
        run_id=uuid4(),
        advertiser="Catalog service",
        screenshot_path="screens/ad.png",
        created_at=now,
        updated_at=now,
    )


async def test_catalog_service_adds_only_backend_media_links() -> None:
    item = ad()
    repository = StubCatalog([item])
    service = AdService(repository, StubMediaLinks())
    query = AdQuery(page=2, page_size=5, country="Spain")

    page = await service.list_ads(query)
    detail = await service.get_ad(item.id)

    assert repository.queries == [query]
    assert page.total == 1
    assert page.page == 2
    assert detail.media.screenshot_url == f"/proxy/{item.id}/screenshot"
    assert detail.media.video_url is None


async def test_catalog_service_raises_domain_not_found() -> None:
    service = AdService(StubCatalog([]), StubMediaLinks())

    with pytest.raises(AdNotFoundError):
        await service.get_ad(uuid4())


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("advertiser", ("advertiser", False)),
        ("-created_at", ("created_at", True)),
        ("unknown", ("captured_at", True)),
    ],
)
def test_catalog_order_normalization(
    value: str,
    expected: tuple[str, bool],
) -> None:
    assert normalize_order(value) == expected
