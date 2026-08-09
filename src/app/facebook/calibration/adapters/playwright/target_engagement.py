from __future__ import annotations

import random
from typing import Any, Protocol

from playwright.sync_api import Page

from ...accounting import offer_funnel_action_ok
from ...execution import EngagementPolicy, plan_engagement
from ...funnel import redact_error
from ...planning import CalibrationTarget
from .comments import post_comment
from .follow import follow_advertiser
from .landing import visit_ad_landing
from .post_viewer import locate_saved_post, view_feed_ad
from .reaction import click_like
from .target_options import CalibrationBrowserOptions


class FunnelSession(Protocol):
    def run(
        self,
        target: CalibrationTarget,
        *,
        source_page: Page | None = None,
        element_id: str = "",
    ) -> dict[str, Any]: ...


class SavedPostEngager:
    def __init__(
        self,
        policy: EngagementPolicy,
        budget: dict[str, int],
        options: CalibrationBrowserOptions,
        *,
        funnel_session: FunnelSession | None = None,
    ) -> None:
        self.policy = policy
        self.budget = budget
        self.options = options
        self.funnel_session = funnel_session

    def engage(
        self,
        page: Page,
        row: dict[str, Any],
        target: CalibrationTarget,
        *,
        relevant_ad_number: int,
        view_seconds: float | None = None,
    ) -> dict[str, Any]:
        element_id = str(row.get("element_id") or "")
        result: dict[str, Any] = {
            "advertiser": str(row.get("advertiser") or ""),
            "displayed_domain": str(row.get("domain") or ""),
            "headline": str(row.get("headline") or ""),
            "element_id": element_id,
            "source": "saved_facebook_post",
            "relevant_ad_number": relevant_ad_number,
            "target_fb_ad_id": target.fb_ad_id,
            "view": safe_action(
                "view",
                view_feed_ad,
                page,
                element_id,
                max(
                    0.0,
                    self.options.view_seconds if view_seconds is None else view_seconds,
                ),
            ),
            "actions": [],
        }
        plan = plan_engagement(
            self.policy,
            self.budget,
            relevant_ad_number=relevant_ad_number,
            comments_available=bool(self.options.comment_templates),
            visit_landing=self.options.visit_landing,
            random_value=random.random,
        )
        if self.options.interaction_dry_run:
            result["actions"] = [
                {"action": action, "status": "dry_run"} for action in plan.due_actions()
            ]
            return result

        if plan.reaction:
            self._reaction(result, page, row, target, element_id)
        if plan.comment:
            self._comment(result, page, row, target, element_id)
        if plan.follow:
            self._follow(result, page, row, target, element_id)
        if plan.landing_visit:
            self._landing(result, page, row, target, element_id)
        return result

    def direct_offer(
        self,
        target: CalibrationTarget,
        *,
        view_status: str,
    ) -> dict[str, Any]:
        if self.funnel_session is None:
            raise RuntimeError("offer funnel session is unavailable")
        self.budget["opened"] = self.budget.get("opened", 0) + 1
        return {
            "view": {"status": view_status},
            "actions": [self.funnel_session.run(target)],
            "relevant_ad_number": self.budget["opened"],
        }

    def _reaction(
        self,
        result: dict[str, Any],
        page: Page,
        row: dict[str, Any],
        target: CalibrationTarget,
        element_id: str,
    ) -> None:
        self.budget["reaction"] += 1
        action = engage_reaction(page, row, element_id, target)
        result["actions"].append(action)
        self.budget["successful"] += int(action.get("status") == "clicked")

    def _comment(
        self,
        result: dict[str, Any],
        page: Page,
        row: dict[str, Any],
        target: CalibrationTarget,
        element_id: str,
    ) -> None:
        self.budget["comment"] += 1
        refreshed = refresh_engagement_row(page, row, target)
        current_id = str((refreshed or row).get("element_id") or element_id)
        action = safe_action(
            "comment",
            post_comment,
            page,
            current_id,
            self.options.comment_templates[0],
        )
        result["actions"].append(action)
        self.budget["successful"] += int(action.get("status") == "posted")

    def _follow(
        self,
        result: dict[str, Any],
        page: Page,
        row: dict[str, Any],
        target: CalibrationTarget,
        element_id: str,
    ) -> None:
        self.budget["follow"] += 1
        refreshed = refresh_engagement_row(page, row, target)
        current_id = str((refreshed or row).get("element_id") or element_id)
        action = safe_action(
            "follow",
            follow_advertiser,
            page,
            current_id,
            str(row.get("advertiser") or ""),
            timeout_ms=self.options.timeout_ms,
        )
        result["actions"].append(action)
        self.budget["successful"] += int(action.get("status") == "clicked")

    def _landing(
        self,
        result: dict[str, Any],
        page: Page,
        row: dict[str, Any],
        target: CalibrationTarget,
        element_id: str,
    ) -> None:
        self.budget["landing_visit"] = self.budget.get("landing_visit", 0) + 1
        refreshed = refresh_engagement_row(page, row, target)
        current_id = str((refreshed or row).get("element_id") or element_id)
        expected_url = target.landing_clean or (
            f"https://{target.displayed_domain}" if target.displayed_domain else ""
        )
        if self.funnel_session is not None:
            action = safe_action(
                "offer_funnel",
                self.funnel_session.run,
                target,
                source_page=page,
                element_id=current_id,
            )
        else:
            action = safe_action(
                "landing_visit",
                visit_ad_landing,
                page,
                current_id,
                cta=target.cta,
                expected_url=expected_url,
                dwell_seconds=self.options.landing_view_seconds,
                timeout_ms=self.options.landing_timeout_ms,
            )
        result["actions"].append(action)
        self.budget["successful"] += int(
            action.get("status") == "visited" or offer_funnel_action_ok(action)
        )


def engage_reaction(
    page: Page,
    row: dict[str, Any],
    element_id: str,
    target: CalibrationTarget,
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    current_element_id = element_id
    for _ in range(3):
        action = safe_action("reaction", click_like, page, current_element_id)
        attempts.append(action)
        status = action.get("status")
        if status == "clicked":
            if len(attempts) > 1:
                action["attempts"] = attempts[:-1]
            return action
        if status == "already_active":
            if any(item.get("status") == "click_unconfirmed" for item in attempts[:-1]):
                return {
                    "action": "reaction",
                    "status": "clicked",
                    "confirmed": True,
                    "confirmation": action,
                    "attempts": attempts[:-1],
                }
            return action
        if status != "click_unconfirmed":
            return action
        refreshed = refresh_engagement_row(page, row, target)
        if refreshed is None or not refreshed.get("element_id"):
            action["attempts"] = attempts[:-1]
            return action
        current_element_id = str(refreshed["element_id"])
    final = attempts[-1]
    final["attempts"] = attempts[:-1]
    return final


def refresh_engagement_row(
    page: Page,
    original: dict[str, Any],
    target: CalibrationTarget,
) -> dict[str, Any] | None:
    try:
        located = locate_saved_post(page, target)
    except Exception:
        return None
    if located.get("status") != "located":
        return None
    return {**original, "element_id": str(located["element_id"])}


def safe_action(
    name: str,
    function: Any,
    *args: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        return {"action": name, **function(*args, **kwargs)}
    except Exception as exc:
        return {"action": name, "status": "failed", "error": redact_error(exc)}
