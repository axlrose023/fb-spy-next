from uuid import UUID

from fastapi import HTTPException

from app.ad_library.ads import AdNotFoundError, AdService
from app.ad_library.ads.adapters.persistence import SqlAlchemyAdRepository
from app.ad_library.ads.schemas import (
    AdResponse,
    AdsPaginationParams,
    AdsPaginationResponse,
    to_page_response,
    to_query,
    to_response,
)
from app.ad_library.media import MediaURLSigner
from app.database.uow import UnitOfWork


class FacebookAdService:
    def __init__(
        self,
        uow: UnitOfWork,
        media_signer: MediaURLSigner,
    ):
        self._service = AdService(SqlAlchemyAdRepository(uow.session), media_signer)

    async def get_ads(self, params: AdsPaginationParams) -> AdsPaginationResponse:
        return to_page_response(await self._service.list_ads(to_query(params)))

    async def get_ad_by_id(self, ad_id: UUID) -> AdResponse:
        try:
            ad = await self._service.get_ad(ad_id)
        except AdNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Ad not found") from exc
        return to_response(ad)
