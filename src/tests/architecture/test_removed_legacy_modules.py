from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

SRC_ROOT = Path(__file__).parents[2]
APP_ROOT = SRC_ROOT / "app"
REMOVED_MODULES = {
    "app.services.facebook": APP_ROOT / "services/facebook/__init__.py",
    "app.services.facebook.calibration": (
        APP_ROOT / "services/facebook/calibration.py"
    ),
    "app.services.facebook.engagement": APP_ROOT / "services/facebook/engagement.py",
    "app.services.facebook.health": APP_ROOT / "services/facebook/health.py",
    "app.services.facebook.importer": APP_ROOT / "services/facebook/importer.py",
    "app.services.facebook.language": APP_ROOT / "services/facebook/language.py",
    "app.services.facebook.landing_archive": (
        APP_ROOT / "services/facebook/landing_archive.py"
    ),
    "app.services.facebook.offer_funnel": (
        APP_ROOT / "services/facebook/offer_funnel.py"
    ),
    "app.services.facebook.runner_process": (
        APP_ROOT / "services/facebook/runner_process.py"
    ),
    "app.services.facebook.relevance": APP_ROOT / "services/facebook/relevance.py",
    "app.services.facebook_db_importer": (
        APP_ROOT / "services/facebook_db_importer.py"
    ),
    "app.services.facebook_isolated_landing_resolver": (
        APP_ROOT / "services/facebook_isolated_landing_resolver.py"
    ),
    "app.services.facebook_relevance_classifier": (
        APP_ROOT / "services/facebook_relevance_classifier.py"
    ),
    "app.services.facebook_ad_enricher": (
        APP_ROOT / "services/facebook_ad_enricher.py"
    ),
    "app.services.facebook_calibrator": APP_ROOT / "services/facebook_calibrator.py",
    "app.services.facebook_runner": APP_ROOT / "services/facebook_runner.py",
    "app.services.facebook_orchestrator": (
        APP_ROOT / "services/facebook_orchestrator.py"
    ),
    "app.services.browser": APP_ROOT / "services/browser/__init__.py",
    "app.services.browser.context": APP_ROOT / "services/browser/context.py",
    "app.services.browser.pool": APP_ROOT / "services/browser/pool.py",
    "app.services.browser.useragent": APP_ROOT / "services/browser/useragent.py",
    "app.services.logging": APP_ROOT / "services/logging.py",
    "app.services.media_storage": APP_ROOT / "services/media_storage.py",
    "app.api.modules.ads.gateway": APP_ROOT / "api/modules/ads/gateway.py",
    "app.api.modules.ads.models": APP_ROOT / "api/modules/ads/models.py",
    "app.api.modules.runs.gateway": APP_ROOT / "api/modules/runs/gateway.py",
    "app.api.modules.runs.models": APP_ROOT / "api/modules/runs/models.py",
    "app.api.modules.users.gateway": APP_ROOT / "api/modules/users/gateway.py",
    "app.api.modules.users.models": APP_ROOT / "api/modules/users/models.py",
    "app.api.modules.ads.routes": APP_ROOT / "api/modules/ads/routes.py",
    "app.api.modules.ads.schema": APP_ROOT / "api/modules/ads/schema.py",
    "app.api.modules.auth.routes": APP_ROOT / "api/modules/auth/routes.py",
    "app.api.modules.auth.schema": APP_ROOT / "api/modules/auth/schema.py",
    "app.api.modules.auth.service": APP_ROOT / "api/modules/auth/service.py",
    "app.api.modules.auth.services.auth": (
        APP_ROOT / "api/modules/auth/services/auth.py"
    ),
    "app.api.modules.media.routes": APP_ROOT / "api/modules/media/routes.py",
    "app.api.modules.runs.routes": APP_ROOT / "api/modules/runs/routes.py",
    "app.api.modules.runs.schema": APP_ROOT / "api/modules/runs/schema.py",
    "app.api.modules.stats.routes": APP_ROOT / "api/modules/stats/routes.py",
    "app.api.modules.stats.schema": APP_ROOT / "api/modules/stats/schema.py",
    "app.api.modules.users.routes": APP_ROOT / "api/modules/users/routes.py",
    "app.api.modules.users.schema": APP_ROOT / "api/modules/users/schema.py",
    "app.api.modules.users.service": APP_ROOT / "api/modules/users/service.py",
}
FORBIDDEN_PRODUCTION_IMPORTS = set(REMOVED_MODULES)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_removed_legacy_module_files_do_not_return() -> None:
    assert all(not path.exists() for path in REMOVED_MODULES.values())


def test_production_does_not_import_removed_legacy_modules() -> None:
    violations: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        removed = sorted(_imports(path) & FORBIDDEN_PRODUCTION_IMPORTS)
        if removed:
            relative = path.relative_to(APP_ROOT)
            violations.append(f"{relative}: {', '.join(removed)}")

    assert violations == []
