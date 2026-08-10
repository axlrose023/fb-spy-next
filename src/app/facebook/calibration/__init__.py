from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .accounting import (
    calibration_goals_met,
    calibration_target_ok,
    interaction_counts,
    offer_funnel_action_ok,
    should_stop_after_target_result,
)
from .adapters import (
    CalibrationProcessEnvironment,
    JsonCalibrationTargetPool,
    build_calibration_command,
    persistent_target_pool,
)
from .adapters.playwright import (
    click_like,
    follow_advertiser,
    locate_saved_post,
    open_ad_landing,
    post_comment,
    view_feed_ad,
    visit_ad_landing,
    wait_for_saved_post,
)
from .contracts import CalibrationResultRecorder, CalibrationTargetExecutor
from .execution import (
    CalibrationPassHooks,
    CalibrationPassRequest,
    CalibrationPassService,
    EngagementPlan,
    EngagementPolicy,
    build_calibration_pass_record,
    calibration_timeout_seconds,
    find_matching_target,
    live_ad_key,
    plan_engagement,
    target_match_score,
)
from .funnel import (
    OfferFunnelPolicy,
    OfferFunnelSession,
    OfferIdentity,
    browse_offer_page,
    click_prelander_cta,
    complete_quiz,
    detect_success,
    domain_allowed,
    fill_offer_form,
    find_offer_form,
    handle_offer_form,
    inspect_offer_form,
    load_offer_identity,
    offer_url,
    public_offer_target,
    redact_error,
    redact_url,
    scroll_prelander,
)
from .models import (
    CalibrationDecision,
    CalibrationLoopPolicy,
    CalibrationPlan,
    CalibrationPolicy,
    CalibrationRunResult,
)
from .planning import (
    CalibrationIntensityPolicy,
    CalibrationTarget,
    baseline_from_history,
    calibration_pool_name,
    effective_target_goal,
    evaluate_calibration_need,
    is_direct_calibration_target,
    is_good_baseline_candidate,
    is_relevant_ad,
    merge_calibration_ads,
    metrics_from_dict,
    plan_calibration_intensity,
    rotate_calibration_targets,
    select_calibration_targets,
)
from .service import CalibrationService

if TYPE_CHECKING:
    from .adapters.persistence import (
        append_event,
        load_engagement_targets_from_ads_json,
        load_saved_facebook_targets_from_ads_json,
        load_targets_from_ads_json,
        load_targets_from_db,
        quarantined_facebook_post_urls,
        record_facebook_post_target_result,
        write_json,
        write_targets,
    )

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
    "CalibrationDecision",
    "CalibrationLoopPolicy",
    "CalibrationIntensityPolicy",
    "CalibrationPlan",
    "CalibrationPassHooks",
    "CalibrationPassRequest",
    "CalibrationPassService",
    "CalibrationPolicy",
    "CalibrationProcessEnvironment",
    "CalibrationRunResult",
    "CalibrationService",
    "CalibrationTarget",
    "CalibrationResultRecorder",
    "CalibrationTargetExecutor",
    "append_event",
    "calibration_pool_name",
    "EngagementPlan",
    "EngagementPolicy",
    "OfferFunnelPolicy",
    "OfferFunnelSession",
    "OfferIdentity",
    "baseline_from_history",
    "browse_offer_page",
    "build_calibration_command",
    "build_calibration_pass_record",
    "calibration_goals_met",
    "calibration_target_ok",
    "calibration_timeout_seconds",
    "click_like",
    "click_prelander_cta",
    "complete_quiz",
    "detect_success",
    "domain_allowed",
    "evaluate_calibration_need",
    "effective_target_goal",
    "find_matching_target",
    "fill_offer_form",
    "find_offer_form",
    "follow_advertiser",
    "handle_offer_form",
    "inspect_offer_form",
    "interaction_counts",
    "is_good_baseline_candidate",
    "is_direct_calibration_target",
    "is_relevant_ad",
    "JsonCalibrationTargetPool",
    "live_ad_key",
    "load_engagement_targets_from_ads_json",
    "load_offer_identity",
    "load_saved_facebook_targets_from_ads_json",
    "load_targets_from_ads_json",
    "load_targets_from_db",
    "locate_saved_post",
    "metrics_from_dict",
    "merge_calibration_ads",
    "open_ad_landing",
    "offer_url",
    "offer_funnel_action_ok",
    "plan_calibration_intensity",
    "plan_engagement",
    "persistent_target_pool",
    "post_comment",
    "public_offer_target",
    "quarantined_facebook_post_urls",
    "redact_error",
    "redact_url",
    "record_facebook_post_target_result",
    "rotate_calibration_targets",
    "select_calibration_targets",
    "should_stop_after_target_result",
    "scroll_prelander",
    "target_match_score",
    "view_feed_ad",
    "visit_ad_landing",
    "wait_for_saved_post",
    "write_json",
    "write_targets",
]


def __getattr__(name: str) -> Any:
    if name not in _PERSISTENCE_EXPORTS:
        raise AttributeError(name)
    from .adapters import persistence

    value = getattr(persistence, name)
    globals()[name] = value
    return value
