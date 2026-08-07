from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from ..models import Ad
from .language import language_from_raw_ad
from .models import AdSource


@dataclass(frozen=True, slots=True)
class AdMappingPolicy:
    data_dir: Path
    default_country: str | None


class AdMapper:
    def __init__(self, policy: AdMappingPolicy) -> None:
        self._data_dir = policy.data_dir.expanduser().resolve()
        self._default_country = policy.default_country

    def map(
        self,
        run_id: UUID,
        source_index: int,
        raw: dict[str, Any],
        run_dir: Path,
        *,
        country_fallback: str | None = None,
    ) -> Ad:
        country = (
            clean_value(raw.get("country") or country_fallback or self._default_country)
            or self._default_country
        )
        return Ad(
            id=uuid4(),
            run_id=run_id,
            source_index=source_index,
            source_key=source_key(raw, source_index),
            advertiser=raw.get("advertiser") or "",
            ad_type=raw.get("ad_type") or "unknown",
            format="video" if raw.get("has_video") else "image",
            country=country,
            language=language_from_raw_ad(raw),
            has_video=bool(raw.get("has_video")),
            displayed_domain=raw.get("displayed_domain") or "",
            headline=raw.get("headline") or "",
            ad_text=raw.get("ad_text") or "",
            cta=raw.get("cta") or "",
            creative_img=raw.get("creative_img") or "",
            video_path=self.media_path(
                run_dir,
                raw.get("video") or raw.get("video_path"),
            ),
            screenshot_path=self.media_path(run_dir, raw.get("screenshot")),
            screenshot_ok=raw.get("screenshot_ok"),
            screenshot_issue=raw.get("screenshot_issue"),
            landing_full=raw.get("landing_full"),
            landing_clean=raw.get("landing_clean"),
            landing_screenshot_path=self.media_path(
                run_dir, raw.get("landing_screenshot")
            ),
            landing_archive_path=self.media_path(
                run_dir, raw.get("landing_archive") or raw.get("landing_archive_path")
            ),
            fb_ad_id=clean_value(raw.get("fb_ad_id")),
            utm=raw.get("utm") or {},
            captured_at=parse_datetime(raw.get("captured_at")),
        )

    def map_sources(
        self,
        run_id: UUID,
        sources: list[AdSource],
        run_dir: Path,
        country_fallback: str | None,
    ) -> list[tuple[AdSource, Ad]]:
        return [
            (
                source,
                self.map(
                    run_id,
                    source.index,
                    source.raw,
                    run_dir,
                    country_fallback=country_fallback,
                ),
            )
            for source in sources
        ]

    def media_path(self, run_dir: Path, value: str | None) -> str:
        if not value:
            return ""
        path = Path(value)
        if not path.is_absolute():
            path = run_dir / path
        try:
            return path.resolve().relative_to(self._data_dir).as_posix()
        except ValueError:
            return str(path)


def clean_value(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def source_key(raw: dict[str, Any], source_index: int) -> str:
    if raw.get("fb_ad_id"):
        return f"fb_ad_id:{raw['fb_ad_id']}"
    parts = [
        raw.get("advertiser") or "",
        raw.get("displayed_domain") or "",
        raw.get("headline") or "",
        raw.get("ad_text") or "",
        raw.get("creative_img") or "",
    ]
    value = "|".join(parts).strip("|")
    return value or f"source_index:{source_index}"


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
