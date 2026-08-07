from uuid import UUID

from fastapi import HTTPException

from app.ad_library.media import MediaKind, MediaURLSigner
from app.api.common.utils import build_filters
from app.api.modules.ads.gateway import build_ad_search_filter
from app.api.modules.ads.models import FacebookAd
from app.api.modules.ads.schema import (
    AdResponse,
    AdsPaginationParams,
    AdsPaginationResponse,
)
from app.database.uow import UnitOfWork


class FacebookAdService:
    def __init__(
        self,
        uow: UnitOfWork,
        media_signer: MediaURLSigner,
    ):
        self.uow = uow
        self.media_signer = media_signer

    async def get_ads(self, params: AdsPaginationParams) -> AdsPaginationResponse:
        data = params.model_dump(exclude_unset=True)
        data.pop("page", None)
        data.pop("page_size", None)
        order_by = data.pop("order_by", "-captured_at")
        query = data.pop("q", None)
        has_landing = data.pop("has_landing", None)
        ad_types = data.pop("ad_type", None)

        filters = build_filters(FacebookAd, data)
        if ad_types:
            filters.append(FacebookAd.ad_type.in_(ad_types))
        if query:
            filters.append(build_ad_search_filter(query))
        if has_landing is True:
            filters.append(FacebookAd.landing_full.is_not(None))
        elif has_landing is False:
            filters.append(FacebookAd.landing_full.is_(None))

        ads = await self.uow.facebook_ads.get_all(
            limit=params.page_size,
            offset=params.offset,
            filters=filters,
            order_by=order_by,
        )
        total = await self.uow.facebook_ads.get_total_count(filters)
        return AdsPaginationResponse(
            total=total,
            items=[self._response(ad) for ad in ads],
            page=params.page,
            page_size=params.page_size,
        )

    async def get_ad_by_id(self, ad_id: UUID) -> AdResponse:
        ad = await self.uow.facebook_ads.get_by_id(ad_id)
        if not ad:
            raise HTTPException(status_code=404, detail="Ad not found")
        return self._response(ad)

    def _response(self, ad: FacebookAd) -> AdResponse:
        response = AdResponse.model_validate(ad)
        return response.model_copy(
            update={
                "screenshot_url": self.media_signer.url_for(
                    ad.id,
                    MediaKind.SCREENSHOT,
                    ad.screenshot_path,
                ),
                "video_url": self.media_signer.url_for(
                    ad.id,
                    MediaKind.VIDEO,
                    ad.video_path,
                ),
                "landing_screenshot_url": self.media_signer.url_for(
                    ad.id,
                    MediaKind.LANDING_SCREENSHOT,
                    ad.landing_screenshot_path,
                ),
                "landing_archive_url": self.media_signer.url_for(
                    ad.id,
                    MediaKind.LANDING_ARCHIVE,
                    ad.landing_archive_path,
                ),
            }
        )
