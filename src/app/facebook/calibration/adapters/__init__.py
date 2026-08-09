from __future__ import annotations

from typing import Any

from .invocation_command import (
    CalibrationProcessEnvironment,
    build_calibration_command,
)
from .json_target_pool import JsonCalibrationTargetPool

_PERSISTENCE_EXPORTS = {
    "append_event",
    "load_engagement_targets_from_ads_json",
    "load_saved_facebook_targets_from_ads_json",
    "load_targets_from_ads_json",
    "load_targets_from_db",
    "quarantined_facebook_post_urls",
    "record_facebook_post_target_result",
    "write_json",
    "write_targets",
}

__all__ = [
    "CalibrationProcessEnvironment",
    "JsonCalibrationTargetPool",
    "build_calibration_command",
    *_PERSISTENCE_EXPORTS,
]


def __getattr__(name: str) -> Any:
    if name not in _PERSISTENCE_EXPORTS:
        raise AttributeError(name)
    from . import persistence

    value = getattr(persistence, name)
    globals()[name] = value
    return value
