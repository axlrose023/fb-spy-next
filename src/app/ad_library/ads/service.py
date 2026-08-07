from __future__ import annotations

from uuid import UUID

from app.ad_library.media import MediaKind

from .contracts import AdCatalogRepository, MediaLinkBuilder
from .exceptions import AdNotFoundError
from .models import Ad, AdCatalogPage, AdMediaLinks, AdQuery, CatalogAd


class AdService:
    def __init__(
        self,
        ads: AdCatalogRepository,
        media_links: MediaLinkBuilder,
    ) -> None:
        self._ads = ads
        self._media_links = media_links

    async def list_ads(self, query: AdQuery) -> AdCatalogPage:
        page = await self._ads.page(query)
        return AdCatalogPage(
            items=[self._catalog_ad(ad) for ad in page.items],
            total=page.total,
            page=page.page,
            page_size=page.page_size,
        )

    async def get_ad(self, ad_id: UUID) -> CatalogAd:
        ad = await self._ads.get(ad_id)
        if ad is None:
            raise AdNotFoundError("ad does not exist")
        return self._catalog_ad(ad)

    def _catalog_ad(self, ad: Ad) -> CatalogAd:
        return CatalogAd(
            ad=ad,
            media=AdMediaLinks(
                screenshot_url=self._media_links.url_for(
                    ad.id,
                    MediaKind.SCREENSHOT,
                    ad.screenshot_path,
                ),
                video_url=self._media_links.url_for(
                    ad.id,
                    MediaKind.VIDEO,
                    ad.video_path,
                ),
                landing_screenshot_url=self._media_links.url_for(
                    ad.id,
                    MediaKind.LANDING_SCREENSHOT,
                    ad.landing_screenshot_path,
                ),
                landing_archive_url=self._media_links.url_for(
                    ad.id,
                    MediaKind.LANDING_ARCHIVE,
                    ad.landing_archive_path,
                ),
            ),
        )
