"""Compatibility facade for the run-owned Facebook ads importer."""

from app.facebook.runs.adapters import (
    FacebookAdsImporter,
    FacebookAdsStreamingImportSession,
)

__all__ = ["FacebookAdsImporter", "FacebookAdsStreamingImportSession"]
