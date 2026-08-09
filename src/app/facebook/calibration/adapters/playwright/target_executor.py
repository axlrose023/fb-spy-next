from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Page
from playwright.sync_api import Error as PlaywrightError

from ...accounting import calibration_target_ok, offer_funnel_action_ok
from ...execution import EngagementPolicy
from ...funnel import offer_url, public_offer_target, redact_error, redact_url
from ...planning import CalibrationTarget
from .navigation import (
    SavedPostAccessError,
    is_browser_context_closed_error,
    is_transient_navigation_error,
    open_saved_post,
)
from .post_viewer import wait_for_saved_post
from .target_engagement import FunnelSession, SavedPostEngager
from .target_options import CalibrationBrowserOptions

EventWriter = Callable[[Path, dict[str, Any]], None]


class SavedPostTargetExecutor:
    def __init__(
        self,
        context: BrowserContext,
        *,
        run_dir: Path,
        events_path: Path,
        policy: EngagementPolicy,
        budget: dict[str, int],
        options: CalibrationBrowserOptions,
        write_event: EventWriter,
        utc_now: Callable[[], str],
        ignore_certificate_errors: Callable[[Page], bool],
        funnel_session: FunnelSession | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.context = context
        self.run_dir = run_dir
        self.events_path = events_path
        self.options = options
        self.write_event = write_event
        self.utc_now = utc_now
        self.ignore_certificate_errors = ignore_certificate_errors
        self.funnel_session = funnel_session
        self.monotonic = monotonic
        self.engager = SavedPostEngager(
            policy,
            budget,
            options,
            funnel_session=funnel_session,
        )
        self.budget = budget

    def execute(
        self,
        target: CalibrationTarget,
        *,
        index: int,
        total: int,
    ) -> dict[str, Any]:
        started = self.monotonic()
        result = _initial_result(target, index)
        self._event(
            "saved_ad_started",
            index=index,
            total=total,
            target=public_offer_target(target),
        )
        page: Page | None = None
        skip_page_close = False
        try:
            if not target.facebook_post_url:
                return self._direct_offer(
                    result,
                    target,
                    started,
                    view_status="post_unavailable",
                )
            page = self.context.new_page()
            try:
                response = open_saved_post(
                    page,
                    target.facebook_post_url,
                    timeout_ms=self.options.timeout_ms,
                    ignore_certificate_errors=self.ignore_certificate_errors,
                )
                result["status"] = response.status if response else None
                result["final_url"] = redact_url(page.url)
            except SavedPostAccessError as exc:
                if self.funnel_session is None or not offer_url(target):
                    raise
                result["source"] = "direct_offer_fallback"
                result["facebook_post_status"] = "access_blocked"
                result["facebook_post_error"] = str(exc)
                return self._direct_offer(
                    result,
                    target,
                    started,
                    view_status="post_access_blocked",
                )

            if self.options.wait_after_load > 0:
                page.wait_for_timeout(round(self.options.wait_after_load * 1000))
            located = wait_for_saved_post(
                page,
                target,
                timeout_ms=max(0, self.options.locate_timeout_ms),
            )
            result["match"] = located
            engagement = self._engage_located(page, target, index, located, result)
            result.update(engagement)
            funnel_ok = any(
                action.get("action") == "offer_funnel"
                and offer_funnel_action_ok(action)
                for action in engagement.get("actions", [])
            )
            post_viewed = engagement.get("view", {}).get("status") == "viewing"
            result["ok"] = calibration_target_ok(
                post_viewed=post_viewed,
                funnel_ok=funnel_ok,
                funnel_required=(
                    self.funnel_session is not None and self.options.visit_landing
                ),
                post_required=located.get("status") == "located",
            )
            if funnel_ok and engagement.get("view", {}).get("status") != "viewing":
                self.budget["successful"] += 1
            if not result["ok"]:
                result["error"] = (
                    f"saved Facebook post view failed: {engagement.get('view')}"
                )
            self._finish(result, started)
        except Exception as exc:
            result["error"] = redact_error(exc)
            transient = is_transient_navigation_error(exc)
            context_closed = is_browser_context_closed_error(exc)
            if transient:
                result["transient_navigation_error"] = True
            if context_closed:
                result["browser_context_closed"] = True
            if isinstance(exc, SavedPostAccessError) or transient or context_closed:
                result["infrastructure_error"] = True
                skip_page_close = True
            self._finish(result, started)
        finally:
            if page is not None and not skip_page_close:
                try:
                    page.close(run_before_unload=False)
                except PlaywrightError:
                    pass
        return result

    def _engage_located(
        self,
        page: Page,
        target: CalibrationTarget,
        index: int,
        located: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        if located.get("status") != "located":
            if self.funnel_session is None:
                raise RuntimeError(f"saved Facebook post not found: {located}")
            self.budget["opened"] = self.budget.get("opened", 0) + 1
            return {
                "view": {"status": "post_not_found", "match": located},
                "actions": [self.funnel_session.run(target)],
                "relevant_ad_number": self.budget["opened"],
            }
        element_id = str(located["element_id"])
        if self.options.screenshots:
            self._screenshot(page, element_id, target, index, result)
        self.budget["opened"] = self.budget.get("opened", 0) + 1
        return self.engager.engage(
            page,
            {
                "element_id": element_id,
                "advertiser": target.advertiser,
                "domain": target.displayed_domain,
                "headline": target.headline,
                "ad_text": target.ad_text,
                "creative_img": target.creative_img,
            },
            target,
            relevant_ad_number=self.budget["opened"],
            view_seconds=max(0.0, self.options.view_seconds),
        )

    def _direct_offer(
        self,
        result: dict[str, Any],
        target: CalibrationTarget,
        started: float,
        *,
        view_status: str,
    ) -> dict[str, Any]:
        if self.funnel_session is None:
            raise RuntimeError("calibration target has no direct Facebook post")
        engagement = self.engager.direct_offer(target, view_status=view_status)
        action = engagement["actions"][0]
        result.update(engagement)
        result["ok"] = offer_funnel_action_ok(action)
        if result["ok"]:
            self.budget["successful"] += 1
        else:
            result["error"] = f"direct offer fallback failed: {action}"
        self._finish(result, started)
        return result

    def _screenshot(
        self,
        page: Page,
        element_id: str,
        target: CalibrationTarget,
        index: int,
        result: dict[str, Any],
    ) -> None:
        try:
            screenshot = (
                self.run_dir
                / "screens"
                / f"{index:04d}_{safe_slug(target.advertiser or 'saved_ad')}.png"
            )
            screenshot.parent.mkdir(parents=True, exist_ok=True)
            page.locator(f'[data-fbspy-id="{element_id}"]').first.screenshot(
                path=str(screenshot),
                timeout=8000,
            )
            result["screenshot"] = str(screenshot.relative_to(self.run_dir))
        except Exception as exc:
            result["screenshot_error"] = redact_error(exc)

    def _finish(self, result: dict[str, Any], started: float) -> None:
        result["duration_seconds"] = round(self.monotonic() - started, 3)
        self._event(
            "saved_ad_finished" if result["ok"] else "saved_ad_failed",
            **result,
        )

    def _event(self, kind: str, **payload: Any) -> None:
        self.write_event(
            self.events_path,
            {"at": self.utc_now(), "kind": kind, **payload},
        )


def _initial_result(target: CalibrationTarget, index: int) -> dict[str, Any]:
    post_url = target.facebook_post_url or ""
    return {
        "index": index,
        "url": post_url,
        "advertiser": target.advertiser,
        "displayed_domain": target.displayed_domain,
        "fb_ad_id": target.fb_ad_id,
        "source": "saved_facebook_post" if post_url else "direct_offer_fallback",
        "ok": False,
        "status": None,
        "final_url": None,
        "error": None,
        "duration_seconds": 0.0,
        "screenshot": None,
        "screenshot_error": None,
        "actions": [],
    }


def safe_slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value)
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return (cleaned or "target")[:40]
