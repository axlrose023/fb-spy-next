"""Compatibility entrypoint for profile calibration."""

from __future__ import annotations

from playwright.sync_api import Error as PlaywrightError

from app.facebook.calibration import (
    OfferFunnelPolicy,
    calibration_target_ok,
    interaction_counts,
    offer_funnel_action_ok,
)
from app.facebook.calibration.adapters.playwright import (
    click_like,
    follow_advertiser,
    locate_saved_post,
    post_comment,
    view_feed_ad,
    visit_ad_landing,
    wait_for_saved_post,
)
from app.facebook.calibration.adapters.playwright.navigation import (
    BROWSER_CONTEXT_CLOSED_ERRORS,
    TRANSIENT_NAVIGATION_ERRORS,
    SavedPostAccessError,
    is_browser_context_closed_error,
    is_transient_navigation_error,
)
from app.facebook.calibration.adapters.playwright.target_engagement import (
    engage_reaction,
    refresh_engagement_row,
    safe_action,
)
from app.facebook.calibration.adapters.playwright.target_executor import safe_slug
from app.facebook.calibration.cli.configuration import (
    engagement_policy,
    load_saved_targets,
    offer_funnel_policy,
    public_args,
    rate,
    resolve_run_dir,
    should_connect_before_targets,
)
from app.facebook.calibration.cli.legacy import (
    calibrate_saved_ad,
    calibration_goals_met,
    direct_offer_engagement,
    engage_row,
    goto_saved_post,
    should_stop_after_result,
)
from app.facebook.calibration.cli.parser import build_parser, validate_args
from app.facebook.calibration.commands import main, request_stop

STOP_REQUESTED = False

__all__ = [
    "BROWSER_CONTEXT_CLOSED_ERRORS",
    "OfferFunnelPolicy",
    "PlaywrightError",
    "STOP_REQUESTED",
    "SavedPostAccessError",
    "TRANSIENT_NAVIGATION_ERRORS",
    "click_like",
    "follow_advertiser",
    "locate_saved_post",
    "main",
    "post_comment",
    "visit_ad_landing",
    "view_feed_ad",
    "wait_for_saved_post",
]

_build_parser = build_parser
_validate_args = validate_args
_should_connect_before_targets = should_connect_before_targets
_load_saved_targets = load_saved_targets
_engagement_policy = engagement_policy
_offer_funnel_policy = offer_funnel_policy
_offer_funnel_action_ok = offer_funnel_action_ok
_calibration_target_ok = calibration_target_ok
_interaction_counts = interaction_counts
_is_transient_navigation_error = is_transient_navigation_error
_is_browser_context_closed_error = is_browser_context_closed_error
_engage_reaction = engage_reaction
_refresh_engagement_row = refresh_engagement_row
_safe_action = safe_action
_rate = rate
_resolve_run_dir = resolve_run_dir
_public_args = public_args
_safe_slug = safe_slug
_calibrate_saved_ad = calibrate_saved_ad
_calibration_goals_met = calibration_goals_met
_direct_offer_engagement = direct_offer_engagement
_engage_row = engage_row
_goto_saved_post = goto_saved_post
_should_stop_after_target_result = should_stop_after_result


def _request_stop(signum: int, frame: object) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True
    request_stop(signum, frame)


if __name__ == "__main__":
    raise SystemExit(main())
