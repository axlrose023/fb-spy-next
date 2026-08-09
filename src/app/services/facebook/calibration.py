"""Compatibility facade for the calibration application."""

from app.facebook.calibration import (
    CalibrationTarget,
    append_event,
    load_engagement_targets_from_ads_json,
    load_saved_facebook_targets_from_ads_json,
    load_targets_from_ads_json,
    load_targets_from_db,
    quarantined_facebook_post_urls,
    record_facebook_post_target_result,
    rotate_calibration_targets,
    select_calibration_targets,
    write_json,
    write_targets,
)

__all__ = [
    "CalibrationTarget",
    "append_event",
    "load_engagement_targets_from_ads_json",
    "load_saved_facebook_targets_from_ads_json",
    "load_targets_from_ads_json",
    "load_targets_from_db",
    "quarantined_facebook_post_urls",
    "record_facebook_post_target_result",
    "rotate_calibration_targets",
    "select_calibration_targets",
    "write_json",
    "write_targets",
]
