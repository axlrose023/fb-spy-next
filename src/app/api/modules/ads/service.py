from uuid import UUID

from fastapi import HTTPException

from app.api.common.utils import build_filters
from app.api.modules.ads.gateway import build_ad_search_filter
from app.api.modules.ads.models import FacebookAd
from app.api.modules.ads.schema import (
    AdResponse,
    AdsPaginationParams,
    AdsPaginationResponse,
)
from app.database.uow import UnitOfWork
from app.services.media_storage import (
    MEDIA_SPECS,
    MediaKind,
    MediaNotFoundError,
    MediaPayload,
    MediaRangeError,
    MediaStorage,
    MediaStorageError,
    MediaTokenError,
    MediaURLSigner,
)


class FacebookAdService:
    def __init__(
        self,
        uow: UnitOfWork,
        media_signer: MediaURLSigner,
        media_storage: MediaStorage,
    ):
        self.uow = uow
        self.media_signer = media_signer
        self.media_storage = media_storage

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

    async def get_media(
        self,
        ad_id: UUID,
        kind: MediaKind,
        token: str,
        *,
        range_header: str | None = None,
        head_only: bool = False,
    ) -> MediaPayload:
        try:
            self.media_signer.verify_token(token, ad_id, kind)
        except MediaTokenError as exc:
            raise HTTPException(status_code=403, detail="Invalid media link") from exc

        ad = await self.uow.facebook_ads.get_by_id(ad_id)
        if not ad:
            raise HTTPException(status_code=404, detail="Media not found")
        reference = getattr(ad, MEDIA_SPECS[kind].model_attribute)
        if not reference:
            raise HTTPException(status_code=404, detail="Media not found")
        try:
            if head_only:
                return await self.media_storage.head(reference, kind, ad_id=ad_id)
            return await self.media_storage.open(
                reference,
                kind,
                ad_id=ad_id,
                range_header=range_header,
            )
        except MediaRangeError as exc:
            headers = {}
            if exc.total_size is not None:
                headers["Content-Range"] = f"bytes */{exc.total_size}"
            raise HTTPException(
                status_code=416,
                detail="Requested range is not satisfiable",
                headers=headers,
            ) from exc
        except MediaNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Media not found") from exc
        except MediaStorageError as exc:
            raise HTTPException(
                status_code=502,
                detail="Media storage is temporarily unavailable",
            ) from exc

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
