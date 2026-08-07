from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class MediaKind(StrEnum):
    SCREENSHOT = "screenshot"
    LANDING_SCREENSHOT = "landing-screenshot"
    VIDEO = "video"
    LANDING_ARCHIVE = "landing-archive"


@dataclass(frozen=True, slots=True)
class MediaSpec:
    model_attribute: str
    directory: str
    object_stem: str
    default_suffix: str
    default_content_type: str
    attachment: bool = False


MEDIA_SPECS: dict[MediaKind, MediaSpec] = {
    MediaKind.SCREENSHOT: MediaSpec(
        model_attribute="screenshot_path",
        directory="screenshots",
        object_stem="feed",
        default_suffix=".png",
        default_content_type="image/png",
    ),
    MediaKind.LANDING_SCREENSHOT: MediaSpec(
        model_attribute="landing_screenshot_path",
        directory="screenshots",
        object_stem="landing-full",
        default_suffix=".png",
        default_content_type="image/png",
    ),
    MediaKind.VIDEO: MediaSpec(
        model_attribute="video_path",
        directory="videos",
        object_stem="creative",
        default_suffix=".mp4",
        default_content_type="video/mp4",
    ),
    MediaKind.LANDING_ARCHIVE: MediaSpec(
        model_attribute="landing_archive_path",
        directory="archives",
        object_stem="landing",
        default_suffix=".zip",
        default_content_type="application/zip",
        attachment=True,
    ),
}

ALLOWED_SUFFIXES: dict[MediaKind, frozenset[str]] = {
    MediaKind.SCREENSHOT: frozenset({".png", ".jpg", ".jpeg", ".webp"}),
    MediaKind.LANDING_SCREENSHOT: frozenset({".png", ".jpg", ".jpeg", ".webp"}),
    MediaKind.VIDEO: frozenset({".mp4", ".webm", ".mov"}),
    MediaKind.LANDING_ARCHIVE: frozenset({".zip"}),
}


@dataclass(slots=True)
class MediaPayload:
    body: Any
    status_code: int
    content_length: int
    content_type: str
    content_range: str | None = None
    total_size: int | None = None
