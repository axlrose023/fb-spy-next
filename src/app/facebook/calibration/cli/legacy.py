from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

from app.facebook.navigation import ignore_proxy_certificate_errors
from app.facebook.timing import utc_now

from ..accounting import calibration_goals_met as goals_met
from ..accounting import should_stop_after_target_result as should_stop
from ..adapters.persistence.artifacts import append_event
from ..adapters.playwright import (
    CalibrationBrowserOptions,
    SavedPostEngager,
    SavedPostTargetExecutor,
)
from ..adapters.playwright.navigation import goto_saved_post as navigate_to_post
from ..execution import EngagementPolicy
from ..funnel import OfferFunnelSession
from ..models import CalibrationLoopPolicy
from ..planning import CalibrationTarget


def loop_policy_from_args(args: argparse.Namespace) -> CalibrationLoopPolicy:
    return CalibrationLoopPolicy(
        min_successful_targets=int(getattr(args, "min_successful_targets", 0)),
        min_interactions=int(getattr(args, "min_interactions", 1)),
        comment_every=max(0, int(getattr(args, "comment_every", 0))),
        max_comments=max(0, int(getattr(args, "max_comments", 0))),
        continue_on_target_navigation_error=bool(
            getattr(args, "continue_on_target_navigation_error", False)
        ),
    )


def should_stop_after_result(
    result: dict[str, Any],
    args: argparse.Namespace,
) -> bool:
    stop: bool = should_stop(result, loop_policy_from_args(args))
    return stop


def calibration_goals_met(
    results: list[dict[str, Any]],
    args: argparse.Namespace,
    *,
    targets_available: int | None = None,
) -> bool:
    complete: bool = goals_met(
        results,
        loop_policy_from_args(args),
        targets_available=targets_available,
    )
    return complete


def browser_options_from_args(args: argparse.Namespace) -> CalibrationBrowserOptions:
    templates = tuple(
        value.strip()
        for value in getattr(args, "comment_template", [])
        if value.strip()
    ) or ("👍",)
    timeout_ms = int(getattr(args, "timeout_ms", 45_000))
    return CalibrationBrowserOptions(
        timeout_ms=timeout_ms,
        locate_timeout_ms=max(0, int(getattr(args, "locate_timeout_ms", 12_000))),
        wait_after_load=float(getattr(args, "wait_after_load", 3.0)),
        screenshots=not bool(getattr(args, "no_screenshots", False)),
        view_seconds=max(0.0, float(getattr(args, "view_seconds", 45.0))),
        interaction_dry_run=bool(getattr(args, "interaction_dry_run", False)),
        comment_templates=templates,
        visit_landing=bool(getattr(args, "visit_landing", False)),
        landing_view_seconds=max(
            0.0, float(getattr(args, "landing_view_seconds", 0.0))
        ),
        landing_timeout_ms=max(1, int(getattr(args, "landing_timeout_ms", timeout_ms))),
    )


def calibrate_saved_ad(
    context: Any,
    target: CalibrationTarget,
    index: int,
    total: int,
    run_dir: Path,
    events_path: Path,
    policy: EngagementPolicy,
    budget: dict[str, int],
    args: argparse.Namespace,
    *,
    funnel_session: OfferFunnelSession | None = None,
) -> dict[str, Any]:
    executor = SavedPostTargetExecutor(
        context,
        run_dir=run_dir,
        events_path=events_path,
        policy=policy,
        budget=budget,
        options=browser_options_from_args(args),
        write_event=append_event,
        utc_now=utc_now,
        ignore_certificate_errors=ignore_proxy_certificate_errors,
        funnel_session=funnel_session,
    )
    result: dict[str, Any] = executor.execute(target, index=index, total=total)
    return result


def engage_row(
    page: Page,
    row: dict[str, Any],
    target: CalibrationTarget,
    policy: EngagementPolicy,
    budget: dict[str, int],
    args: argparse.Namespace,
    *,
    relevant_ad_number: int,
    view_seconds: float | None = None,
    funnel_session: OfferFunnelSession | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = SavedPostEngager(
        policy,
        budget,
        browser_options_from_args(args),
        funnel_session=funnel_session,
    ).engage(
        page,
        row,
        target,
        relevant_ad_number=relevant_ad_number,
        view_seconds=view_seconds,
    )
    return result


def direct_offer_engagement(
    funnel_session: OfferFunnelSession,
    target: CalibrationTarget,
    budget: dict[str, int],
    *,
    view_status: str,
) -> dict[str, Any]:
    budget["opened"] = budget.get("opened", 0) + 1
    return {
        "view": {"status": view_status},
        "actions": [funnel_session.run(target)],
        "relevant_ad_number": budget["opened"],
    }


def goto_saved_post(
    page: Page,
    url: str,
    *,
    timeout_ms: int,
    attempts: int = 3,
) -> Any:
    return navigate_to_post(
        page,
        url,
        timeout_ms=timeout_ms,
        attempts=attempts,
        ignore_certificate_errors=ignore_proxy_certificate_errors,
    )
