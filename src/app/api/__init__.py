from fastapi import APIRouter


def register_routers(router: APIRouter) -> None:
    from app.accounts.auth.router import router as auth_router
    from app.accounts.users.router import router as users_router
    from app.ad_library.ads.router import router as ads_router
    from app.ad_library.media.router import router as media_router
    from app.ad_library.statistics.router import router as stats_router
    from app.api.modules.runs.routes import router as runs_router

    router.include_router(auth_router, prefix="/auth", tags=["Auth"])
    router.include_router(media_router, prefix="/media", tags=["Media"])
    router.include_router(users_router, prefix="/users", tags=["Users"])
    router.include_router(ads_router, prefix="/ads", tags=["Ads"])
    router.include_router(runs_router, prefix="/runs", tags=["Runs"])
    router.include_router(stats_router, prefix="/stats", tags=["Stats"])
