from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends

from app.accounts.auth import AuthenticateUser, CurrentUser

from .schemas import AdsStatsResponse, to_response
from .service import StatisticsService

router = APIRouter(route_class=DishkaRoute)


@router.get("/ads", response_model=AdsStatsResponse)
async def get_ads_stats(
    service: FromDishka[StatisticsService],
    _current_user: CurrentUser = Depends(AuthenticateUser()),
) -> AdsStatsResponse:
    return to_response(await service.get_ads_stats())
