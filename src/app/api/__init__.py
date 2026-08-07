from fastapi import APIRouter


def register_routers(router: APIRouter) -> None:
    from app.accounts.auth.router import router as auth_router
    from app.api.modules.ads.routes import router as ads_router
    from app.api.modules.media.routes import router as media_router
    from app.api.modules.runs.routes import router as runs_router
    from app.api.modules.stats.routes import router as stats_router
    from app.api.modules.users.routes import router as users_router

    router.include_router(auth_router, prefix="/auth", tags=["Auth"])
    router.include_router(media_router, prefix="/media", tags=["Media"])
    router.include_router(users_router, prefix="/users", tags=["Users"])
    router.include_router(ads_router, prefix="/ads", tags=["Ads"])
    router.include_router(runs_router, prefix="/runs", tags=["Runs"])
    router.include_router(stats_router, prefix="/stats", tags=["Stats"])
