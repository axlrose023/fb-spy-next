from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Depends

from app.api.modules.auth.services import AuthenticateUser
from app.api.modules.stats.schema import AdsStatsResponse
from app.api.modules.stats.service import StatsService
from app.api.modules.users.models import User

router = APIRouter(route_class=DishkaRoute)


@router.get("/ads", response_model=AdsStatsResponse)
async def get_ads_stats(
    service: FromDishka[StatsService],
    _current_user: User = Depends(AuthenticateUser()),
) -> AdsStatsResponse:
    return await service.get_ads_stats()
