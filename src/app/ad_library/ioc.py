from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession

from app.ad_library.ads import AdService
from app.ad_library.ads.adapters.persistence import FacebookAd, SqlAlchemyAdRepository
from app.ad_library.media import (
    MediaService,
    MediaStorage,
    MediaURLSigner,
)
from app.ad_library.media.adapters.ads import AdMediaReader
from app.ad_library.media.configuration import configured_signer, configured_storage
from app.ad_library.statistics import StatisticsService
from app.ad_library.statistics.adapters import SqlAlchemyAdStatisticsReader
from app.settings import Config


class AdLibraryProvider(Provider):
    @provide(scope=Scope.APP)
    def get_media_signer(self, config: Config) -> MediaURLSigner:
        return configured_signer(config)

    @provide(scope=Scope.APP)
    def get_media_storage(self, config: Config) -> MediaStorage:
        return configured_storage(config)

    @provide(scope=Scope.REQUEST)
    def get_ad_repository(
        self,
        session: AsyncSession,
    ) -> SqlAlchemyAdRepository:
        return SqlAlchemyAdRepository(session)

    @provide(scope=Scope.REQUEST)
    def get_media_service(
        self,
        ads: SqlAlchemyAdRepository,
        media_storage: MediaStorage,
        media_signer: MediaURLSigner,
    ) -> MediaService:
        return MediaService(
            AdMediaReader(ads),
            media_storage,
            media_signer,
        )

    @provide(scope=Scope.REQUEST)
    async def get_ad_service(
        self,
        ads: SqlAlchemyAdRepository,
        media_signer: MediaURLSigner,
    ) -> AdService:
        return AdService(ads, media_signer)

    @provide(scope=Scope.REQUEST)
    def get_statistics_reader(
        self,
        session: AsyncSession,
    ) -> SqlAlchemyAdStatisticsReader:
        return SqlAlchemyAdStatisticsReader(session, FacebookAd)

    @provide(scope=Scope.REQUEST)
    def get_stats_service(
        self,
        reader: SqlAlchemyAdStatisticsReader,
    ) -> StatisticsService:
        return StatisticsService(reader)
