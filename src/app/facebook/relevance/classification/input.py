from __future__ import annotations

from typing import Any


def analysis_input(
    raw: dict[str, Any],
    *,
    include_video: bool,
    feed_only: bool,
) -> dict[str, Any]:
    excluded: set[str] = set()
    if not include_video:
        excluded.update({"video", "video_path"})
    if feed_only:
        excluded.update(
            {
                "landing_full",
                "landing_clean",
                "landing_screenshot",
                "landing_archive",
                "utm",
            }
        )
    return {key: value for key, value in raw.items() if key not in excluded}
