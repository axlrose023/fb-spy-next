from __future__ import annotations

import threading

from .json_target_pool import JsonCalibrationTargetPool
from .persistence.json_targets import load_saved_facebook_targets_from_ads_json
from .persistence.target_health import quarantined_facebook_post_urls

_TARGET_POOL = JsonCalibrationTargetPool(
    load_saved_facebook_targets_from_ads_json,
    quarantined_facebook_post_urls,
    lock=threading.Lock(),
)


def persistent_target_pool() -> JsonCalibrationTargetPool:
    """Return the process-wide pool used by concurrent orchestrator cycles."""

    return _TARGET_POOL
