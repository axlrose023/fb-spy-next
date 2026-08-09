from __future__ import annotations

from pathlib import Path

import pytest

from tests.architecture import test_module_boundaries as boundaries

pytestmark = pytest.mark.architecture


def _use_temporary_source_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    src_root = tmp_path / "src"
    app_root = src_root / "app"
    monkeypatch.setattr(boundaries, "SRC_ROOT", src_root)
    monkeypatch.setattr(boundaries, "APP_ROOT", app_root)
    return app_root


def _write(app_root: Path, relative: str, source: str = "") -> None:
    path = app_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_generic_package_names_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app_root = _use_temporary_source_root(monkeypatch, tmp_path)
    _write(app_root, "facebook/collection/utils.py")

    with pytest.raises(AssertionError, match="Generic module names"):
        boundaries.test_new_modules_do_not_use_generic_dumping_ground_names()


def test_framework_imports_from_inner_layer_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app_root = _use_temporary_source_root(monkeypatch, tmp_path)
    _write(app_root, "facebook/collection/service.py", "import sqlalchemy\n")

    with pytest.raises(AssertionError, match="Inner layer imports outer details"):
        boundaries.test_inner_layers_do_not_import_frameworks_or_adapters()


def test_legacy_infrastructure_imports_from_inner_layer_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app_root = _use_temporary_source_root(monkeypatch, tmp_path)
    _write(
        app_root,
        "ad_library/media/service.py",
        "from app.database.uow import UnitOfWork\n",
    )

    with pytest.raises(AssertionError, match="Inner layer imports outer details"):
        boundaries.test_inner_layers_do_not_import_frameworks_or_adapters()


def test_importing_another_module_internals_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app_root = _use_temporary_source_root(monkeypatch, tmp_path)
    _write(
        app_root,
        "facebook/collection/service.py",
        "from app.facebook.relevance.classification.rules import decide\n",
    )

    with pytest.raises(AssertionError, match="through __init__.py"):
        boundaries.test_cross_module_imports_use_public_package_api()


def test_application_ioc_may_compose_its_own_adapters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app_root = _use_temporary_source_root(monkeypatch, tmp_path)
    _write(
        app_root,
        "ad_library/ioc.py",
        "from app.ad_library.media.adapters.ads import AdMediaReader\n",
    )

    boundaries.test_cross_module_imports_use_public_package_api()
