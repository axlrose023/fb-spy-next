from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, Path
from fastapi.params import Query

from app.accounts.auth import AuthenticateUser, CurrentUser
from app.api.modules.ads.schema import (
    AdResponse,
    AdsPaginationParams,
    AdsPaginationResponse,
)
from app.api.modules.ads.service import FacebookAdService

router = APIRouter(route_class=DishkaRoute)


@router.get("", response_model=AdsPaginationResponse)
async def get_ads(
    service: FromDishka[FacebookAdService],
    params: AdsPaginationParams = Query(),
    _current_user: CurrentUser = Depends(AuthenticateUser()),
) -> AdsPaginationResponse:
    return await service.get_ads(params=params)


@router.get("/{ad_id}", response_model=AdResponse)
async def get_ad_by_id(
    service: FromDishka[FacebookAdService],
    ad_id: UUID = Path(...),
    _current_user: CurrentUser = Depends(AuthenticateUser()),
) -> AdResponse:
    return await service.get_ad_by_id(ad_id)
