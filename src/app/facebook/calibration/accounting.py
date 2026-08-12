from __future__ import annotations

from typing import Any

from .models import CalibrationLoopPolicy

FUNNEL_SUCCESS_STATUSES = {
    "landing_opened",
    "offer_engaged",
    "form_ready",
    "form_submitted_unconfirmed",
    "success_confirmed",
    "unsafe_form_blocked",
}
FUNNEL_BLOCKED_FORM_STATUSES = {
    "identity_missing",
    "invalid_submit_mode",
    "repeat_submit_blocked",
    "required_contact_fields_not_filled",
    "submit_control_not_found",
    "submit_domain_not_allowed",
}
FUNNEL_UNUSABLE_STATUSES = {
    "direct_navigation_failed",
    "missing_direct_offer_url",
    "redirected_without_offer_signals",
}


def offer_funnel_action_ok(action: dict[str, Any]) -> bool:
    return (
        action.get("action") == "offer_funnel"
        and action.get("status") in FUNNEL_SUCCESS_STATUSES
    )


def calibration_target_ok(
    *,
    post_viewed: bool,
    funnel_ok: bool,
    funnel_required: bool,
    post_required: bool,
) -> bool:
    if funnel_required:
        return funnel_ok and (post_viewed or not post_required)
    return post_viewed or funnel_ok


def interaction_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    counts = _empty_counts(results)
    for result in results:
        for action in result.get("actions", []):
            if action.get("action") == "offer_funnel":
                _count_funnel_action(counts, action)
            else:
                _count_standard_action(counts, action)
    return counts


def calibration_goals_met(
    results: list[dict[str, Any]],
    policy: CalibrationLoopPolicy,
    *,
    targets_available: int | None = None,
) -> bool:
    if policy.min_successful_targets <= 0:
        return False
    required_opened = policy.min_successful_targets
    if (
        policy.max_comments > 0
        and policy.comment_every > 0
        and targets_available is not None
        and targets_available >= policy.comment_every
    ):
        required_opened = max(required_opened, policy.comment_every)
    if sum(1 for result in results if result.get("ok")) < required_opened:
        return False
    return interaction_counts(results)["successful"] >= policy.min_interactions


def should_stop_after_target_result(
    result: dict[str, Any],
    policy: CalibrationLoopPolicy,
) -> bool:
    if not result.get("infrastructure_error"):
        return False
    return not (
        policy.continue_on_target_navigation_error
        and result.get("transient_navigation_error") is True
        and result.get("browser_context_closed") is not True
    )


def _empty_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    opened = sum(
        1
        for result in results
        if result.get("view", {}).get("status") == "viewing"
        or ("view" not in result and result.get("ok"))
    )
    return {
        "targets_attempted": len(results),
        "posts_opened": opened,
        "relevant_ads": sum(1 for result in results if result.get("ok")),
        "reaction": 0,
        "comment": 0,
        "follow": 0,
        "landing_visit": 0,
        "offer_funnel": 0,
        "funnel_success_confirmed": 0,
        "funnel_forms_detected": 0,
        "funnel_form_ready": 0,
        "funnel_offer_engaged": 0,
        "funnel_submit_attempted": 0,
        "funnel_submit_blocked": 0,
        "funnel_unsafe_form_blocked": 0,
        "funnel_stale_redirects": 0,
        "funnel_landing_only": 0,
        "funnel_unusable_offers": 0,
        "direct_offer_fallback": 0,
        "direct_offer_fallback_attempts": 0,
        "successful": 0,
        "satisfied": 0,
        "already_active": 0,
        "failed": 0,
    }


def _count_funnel_action(counts: dict[str, int], action: dict[str, Any]) -> None:
    status = str(action.get("status") or "")
    form_status = str(action.get("form_status") or "")
    direct_offer = action.get("opening") == "direct_offer"
    landing_visited = any(
        step.get("action") == "landing_visit" and step.get("status") == "visited"
        for step in action.get("steps", [])
        if isinstance(step, dict)
    )
    counts["landing_visit"] += int(landing_visited)
    counts["direct_offer_fallback_attempts"] += int(direct_offer)
    counts["funnel_forms_detected"] += int(bool(action.get("form_detected")))
    counts["funnel_submit_attempted"] += int(bool(action.get("form_submitted")))
    counts["funnel_submit_blocked"] += int(form_status in FUNNEL_BLOCKED_FORM_STATUSES)
    counts["funnel_unsafe_form_blocked"] += int(status == "unsafe_form_blocked")
    counts["funnel_stale_redirects"] += int(
        status == "redirected_without_offer_signals"
    )
    counts["funnel_landing_only"] += int(status == "landing_viewed")
    counts["funnel_unusable_offers"] += int(status in FUNNEL_UNUSABLE_STATUSES)
    if offer_funnel_action_ok(action):
        counts["offer_funnel"] += 1
        counts["successful"] += 1
        counts["satisfied"] += 1
        counts["funnel_success_confirmed"] += int(status == "success_confirmed")
        counts["funnel_form_ready"] += int(status == "form_ready")
        counts["funnel_offer_engaged"] += int(
            status not in {"success_confirmed", "form_ready"}
        )
        counts["direct_offer_fallback"] += int(direct_offer)
    elif status != "dry_run":
        counts["failed"] += 1


def _count_standard_action(counts: dict[str, int], action: dict[str, Any]) -> None:
    name = str(action.get("action") or "")
    status = str(action.get("status") or "")
    success_status = {
        "reaction": "clicked",
        "comment": "posted",
        "follow": "clicked",
        "landing_visit": "visited",
    }
    if status == "already_active":
        counts["already_active"] += 1
        counts["satisfied"] += 1
    elif success_status.get(name) == status:
        counts[name] += 1
        counts["successful"] += 1
        counts["satisfied"] += 1
    elif status != "dry_run":
        counts["failed"] += 1
