"""Compatibility facade for calibration matching and browser engagement."""

from app.facebook.calibration import (
    EngagementPolicy,
    click_like,
    find_matching_target,
    follow_advertiser,
    live_ad_key,
    locate_saved_post,
    open_ad_landing,
    post_comment,
    target_match_score,
    view_feed_ad,
    visit_ad_landing,
    wait_for_saved_post,
)

__all__ = [
    "EngagementPolicy",
    "click_like",
    "find_matching_target",
    "follow_advertiser",
    "live_ad_key",
    "locate_saved_post",
    "open_ad_landing",
    "post_comment",
    "target_match_score",
    "view_feed_ad",
    "visit_ad_landing",
    "wait_for_saved_post",
]
