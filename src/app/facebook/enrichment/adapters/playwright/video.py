from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.facebook.collection import CollectedAd

from ...models import EnrichmentOptions
from ...video.adapters.playwright import record_ad_video


def record_video(
    page: Any,
    ad: CollectedAd,
    element_id: str,
    *,
    sequence: int,
    run_dir: Path,
    options: EnrichmentOptions,
) -> tuple[bool, str | None]:
    video_path = (
        run_dir / "videos" / f"{sequence:04d}_{safe_slug(ad.advertiser or 'ad')}.mp4"
    )
    ok, issue = record_ad_video(
        page,
        video_path,
        element_id,
        max_seconds=options.video_max_seconds,
    )
    if ok:
        ad.video = str(video_path.relative_to(run_dir))
    return ok, issue


def safe_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")[:32] or "ad"
