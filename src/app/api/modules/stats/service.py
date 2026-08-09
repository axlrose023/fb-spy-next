from app.ad_library.ads.adapters.persistence import FacebookAd
from app.ad_library.statistics import StatisticsService
from app.ad_library.statistics.adapters import SqlAlchemyAdStatisticsReader
from app.ad_library.statistics.schemas import AdsStatsResponse, to_response
from app.database.uow import UnitOfWork


class StatsService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._service = StatisticsService(
            SqlAlchemyAdStatisticsReader(uow.session, FacebookAd)
        )

    async def get_ads_stats(self) -> AdsStatsResponse:
        return to_response(await self._service.get_ads_stats())
