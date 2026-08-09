from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .imports import LegacyRunAdsImporter, RunArtifactDirectoryStager

if TYPE_CHECKING:
    from .importing import FacebookAdsImporter, FacebookAdsStreamingImportSession

__all__ = [
    "FacebookAdsImporter",
    "FacebookAdsStreamingImportSession",
    "LegacyRunAdsImporter",
    "RunArtifactDirectoryStager",
]


def __getattr__(name: str) -> Any:
    if name not in {"FacebookAdsImporter", "FacebookAdsStreamingImportSession"}:
        raise AttributeError(name)
    from . import importing

    value = getattr(importing, name)
    globals()[name] = value
    return value
