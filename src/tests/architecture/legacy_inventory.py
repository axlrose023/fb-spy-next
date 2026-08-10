from pathlib import Path

APP_ROOT = Path(__file__).parents[2] / "app"

FORBIDDEN_IMPORT_PREFIXES = ("app.api.modules", "app.services")

REMOVED_PACKAGE_MODULES = {
    "app.api.modules.ads",
    "app.api.modules.auth",
    "app.api.modules.auth.services",
    "app.api.modules.media",
    "app.api.modules.runs",
    "app.api.modules.stats",
    "app.api.modules.users",
    "app.services",
    "app.services.browser",
    "app.services.facebook",
}

REMOVED_MODULE_NAMES = (
    "app.api.modules.ads",
    "app.api.modules.ads.gateway",
    "app.api.modules.ads.models",
    "app.api.modules.ads.routes",
    "app.api.modules.ads.schema",
    "app.api.modules.ads.service",
    "app.api.modules.auth",
    "app.api.modules.auth.routes",
    "app.api.modules.auth.schema",
    "app.api.modules.auth.service",
    "app.api.modules.auth.services",
    "app.api.modules.auth.services.auth",
    "app.api.modules.auth.services.jwt",
    "app.api.modules.media",
    "app.api.modules.media.routes",
    "app.api.modules.runs",
    "app.api.modules.runs.gateway",
    "app.api.modules.runs.models",
    "app.api.modules.runs.routes",
    "app.api.modules.runs.schema",
    "app.api.modules.runs.service",
    "app.api.modules.stats",
    "app.api.modules.stats.routes",
    "app.api.modules.stats.schema",
    "app.api.modules.stats.service",
    "app.api.modules.users",
    "app.api.modules.users.gateway",
    "app.api.modules.users.models",
    "app.api.modules.users.routes",
    "app.api.modules.users.schema",
    "app.api.modules.users.service",
    "app.services",
    "app.services.browser",
    "app.services.browser.context",
    "app.services.browser.pool",
    "app.services.browser.useragent",
    "app.services.facebook",
    "app.services.facebook.calibration",
    "app.services.facebook.engagement",
    "app.services.facebook.health",
    "app.services.facebook.importer",
    "app.services.facebook.language",
    "app.services.facebook.landing_archive",
    "app.services.facebook.offer_funnel",
    "app.services.facebook.relevance",
    "app.services.facebook.runner_process",
    "app.services.facebook_ad_enricher",
    "app.services.facebook_calibrator",
    "app.services.facebook_db_importer",
    "app.services.facebook_isolated_landing_resolver",
    "app.services.facebook_orchestrator",
    "app.services.facebook_relevance_classifier",
    "app.services.facebook_runner",
    "app.services.logging",
    "app.services.media_storage",
)


def _module_path(module: str) -> Path:
    path = APP_ROOT.joinpath(*module.split(".")[1:])
    if module in REMOVED_PACKAGE_MODULES:
        return path / "__init__.py"
    return path.with_suffix(".py")


REMOVED_MODULES = {module: _module_path(module) for module in REMOVED_MODULE_NAMES}
