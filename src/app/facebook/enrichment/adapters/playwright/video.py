from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.services import facebook_runner

from ...models import EnrichmentOptions


def record_video(
    page: Any,
    ad: facebook_runner.Ad,
    element_id: str,
    *,
    sequence: int,
    run_dir: Path,
    options: EnrichmentOptions,
) -> tuple[bool, str | None]:
    video_path = (
        run_dir / "videos" / f"{sequence:04d}_{safe_slug(ad.advertiser or 'ad')}.mp4"
    )
    ok, issue = facebook_runner.record_ad_video(
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
