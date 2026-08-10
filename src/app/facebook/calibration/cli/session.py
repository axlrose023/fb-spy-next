from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from playwright.sync_api import sync_playwright

from app.facebook.navigation import ignore_proxy_certificate_errors
from app.facebook.timing import utc_now

from ..adapters.persistence.artifacts import append_event
from ..adapters.playwright import SavedPostTargetExecutor
from ..funnel import OfferFunnelSession, load_offer_identity
from ..models import CalibrationRunResult
from ..planning import CalibrationTarget
from ..service import CalibrationService
from .artifacts import CalibrationArtifacts
from .configuration import (
    browser_options,
    engagement_policy,
    loop_policy,
    offer_funnel_policy,
)


def run_browser_session(
    args: argparse.Namespace,
    *,
    ws_endpoint: str,
    targets: list[CalibrationTarget],
    profile_uuid: str,
    selected_country: str | None,
    artifacts: CalibrationArtifacts,
    stop_requested: Callable[[], bool],
) -> tuple[CalibrationRunResult, dict[str, Any]]:
    identity = None
    if args.offer_funnel:
        identity = load_offer_identity(
            args.offer_identity_json,
            profile_uuid=profile_uuid,
            country=selected_country,
        )
        if args.offer_submit_mode == "allowlisted" and not identity.complete:
            raise ValueError(
                "The selected offer identity must include a first name, valid "
                "email and phone before allowlisted submission is enabled"
            )

    funnel_summary: dict[str, Any] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(ws_endpoint)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        funnel_session = (
            OfferFunnelSession(
                context,
                policy=offer_funnel_policy(args),
                identity=identity,
            )
            if args.offer_funnel
            else None
        )
        budget = {
            "reaction": 0,
            "follow": 0,
            "comment": 0,
            "landing_visit": 0,
            "successful": 0,
        }
        executor = SavedPostTargetExecutor(
            context,
            run_dir=artifacts.run_dir,
            events_path=artifacts.events_path,
            policy=engagement_policy(args),
            budget=budget,
            options=browser_options(args),
            write_event=append_event,
            utc_now=utc_now,
            ignore_certificate_errors=ignore_proxy_certificate_errors,
            funnel_session=funnel_session,
        )
        service = CalibrationService(
            executor,
            record_result=artifacts.record_result,
            stop_requested=stop_requested,
        )
        try:
            result = service.run(targets, loop_policy(args))
        finally:
            if funnel_session is not None:
                funnel_summary = funnel_session.summary()
                funnel_session.close()
    return result, funnel_summary
