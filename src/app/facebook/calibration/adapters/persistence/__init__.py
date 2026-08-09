from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .artifacts import append_event, write_json, write_targets
    from .database_targets import load_targets_from_db
    from .json_targets import (
        load_engagement_targets_from_ads_json,
        load_saved_facebook_targets_from_ads_json,
        load_targets_from_ads_json,
    )
    from .target_health import (
        quarantined_facebook_post_urls,
        record_facebook_post_target_result,
    )

_EXPORTS = {
    "append_event": ("artifacts", "append_event"),
    "load_engagement_targets_from_ads_json": (
        "json_targets",
        "load_engagement_targets_from_ads_json",
    ),
    "load_saved_facebook_targets_from_ads_json": (
        "json_targets",
        "load_saved_facebook_targets_from_ads_json",
    ),
    "load_targets_from_ads_json": ("json_targets", "load_targets_from_ads_json"),
    "load_targets_from_db": ("database_targets", "load_targets_from_db"),
    "quarantined_facebook_post_urls": (
        "target_health",
        "quarantined_facebook_post_urls",
    ),
    "record_facebook_post_target_result": (
        "target_health",
        "record_facebook_post_target_result",
    ),
    "write_json": ("artifacts", "write_json"),
    "write_targets": ("artifacts", "write_targets"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute = target
    module = __import__(f"{__name__}.{module_name}", fromlist=[attribute])
    value = getattr(module, attribute)
    globals()[name] = value
    return value
