from typing import Annotated
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.params import Query

from app.accounts.auth import AuthenticateUser, CurrentUser

from .exceptions import AdNotFoundError
from .schemas import (
    AdResponse,
    AdsPaginationParams,
    AdsPaginationResponse,
    to_page_response,
    to_query,
    to_response,
)
from .service import AdService

router = APIRouter(route_class=DishkaRoute)


@router.get("", response_model=AdsPaginationResponse)
async def get_ads(
    service: FromDishka[AdService],
    params: Annotated[AdsPaginationParams, Query()],
    _current_user: CurrentUser = Depends(AuthenticateUser()),
) -> AdsPaginationResponse:
    return to_page_response(await service.list_ads(to_query(params)))


@router.get("/{ad_id}", response_model=AdResponse)
async def get_ad_by_id(
    service: FromDishka[AdService],
    ad_id: UUID = Path(...),
    _current_user: CurrentUser = Depends(AuthenticateUser()),
) -> AdResponse:
    try:
        ad = await service.get_ad(ad_id)
    except AdNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Ad not found") from exc
    return to_response(ad)
