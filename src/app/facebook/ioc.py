from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession

from app.ad_library.media import MediaStorage
from app.database.uow import UnitOfWork
from app.facebook.runs import RunDefaults, RunService
from app.facebook.runs.adapters import (
    FacebookAdsImporter,
    LegacyRunAdsImporter,
    RunArtifactDirectoryStager,
)
from app.facebook.runs.adapters.persistence import (
    SqlAlchemyRunRepository,
    SqlAlchemyRunTransaction,
)
from app.facebook.runs.adapters.processes import FacebookRunnerRegistry
from app.settings import Config


class FacebookProvider(Provider):
    @provide(scope=Scope.APP)
    def get_facebook_ads_importer(
        self,
        config: Config,
        media_storage: MediaStorage,
    ) -> FacebookAdsImporter:
        return FacebookAdsImporter(config, media_storage)

    @provide(scope=Scope.APP)
    def get_facebook_runner_registry(
        self,
        config: Config,
        importer: FacebookAdsImporter,
    ) -> FacebookRunnerRegistry:
        return FacebookRunnerRegistry(config, importer)

    @provide(scope=Scope.REQUEST)
    def get_run_service(
        self,
        session: AsyncSession,
        uow: UnitOfWork,
        config: Config,
        importer: FacebookAdsImporter,
        runner_registry: FacebookRunnerRegistry,
    ) -> RunService:
        facebook = config.facebook
        return RunService(
            SqlAlchemyRunRepository(session),
            SqlAlchemyRunTransaction(session),
            runner_registry,
            LegacyRunAdsImporter(uow, importer),
            RunArtifactDirectoryStager(facebook.data_dir),
            RunDefaults(
                minutes=facebook.default_minutes,
                collect_scrolls=facebook.default_collect_scrolls,
                resolve_max=facebook.default_resolve_max,
                scroll_px=facebook.default_scroll_px,
                octo_profile_uuid=facebook.octo_profile_uuid,
            ),
        )
