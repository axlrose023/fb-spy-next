from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.facebook.calibration import (
    load_saved_facebook_targets_from_ads_json,
    quarantined_facebook_post_urls,
)

from ..adapters.playwright import CalibrationBrowserOptions
from ..execution import EngagementPolicy
from ..funnel import OfferFunnelPolicy
from ..models import CalibrationLoopPolicy
from ..planning import CalibrationTarget, rotate_calibration_targets


def should_connect_before_targets(args: argparse.Namespace) -> bool:
    if not args.dry_run:
        return True
    return not (args.country or args.no_country_filter)


def load_saved_targets(
    args: argparse.Namespace,
    selected_country: str | None,
) -> list[CalibrationTarget]:
    if not args.ads_json:
        return []
    targets = load_saved_facebook_targets_from_ads_json(
        args.ads_json,
        country=selected_country,
        limit=1000,
        include_direct_offers=bool(args.offer_funnel and args.direct_offer_fallback),
        excluded_urls=quarantined_facebook_post_urls(args.target_health_json),
    )
    selected: list[CalibrationTarget] = rotate_calibration_targets(
        targets,
        args.target_offset,
    )[: max(0, args.limit)]
    return selected


def engagement_policy(args: argparse.Namespace) -> EngagementPolicy:
    return EngagementPolicy(
        reaction_rate=rate(args.reaction_rate),
        follow_rate=rate(args.follow_rate),
        comment_every=max(0, args.comment_every),
        max_reactions=max(0, args.max_reactions),
        max_follows=max(0, args.max_follows),
        max_comments=max(0, args.max_comments),
        min_interactions=max(0, args.min_interactions),
    )


def offer_funnel_policy(args: argparse.Namespace) -> OfferFunnelPolicy:
    return OfferFunnelPolicy(
        enabled=bool(args.offer_funnel),
        direct_offer_fallback=bool(args.direct_offer_fallback),
        browse_seconds=max(0.0, float(args.landing_view_seconds)),
        max_scrolls=max(0, int(args.prelander_max_scrolls)),
        quiz_max_questions=max(0, int(args.quiz_max_questions)),
        submit_mode=str(args.offer_submit_mode),
        submit_allow_domains=tuple(args.offer_submit_allow_domain),
        success_wait_seconds=max(0.0, float(args.offer_success_wait_seconds)),
        max_retained_tabs=max(1, int(args.max_retained_offer_tabs)),
        navigation_timeout_ms=max(1, int(args.landing_timeout_ms)),
    )


def loop_policy(args: argparse.Namespace) -> CalibrationLoopPolicy:
    return CalibrationLoopPolicy(
        session_seconds=max(0.0, float(args.session_minutes)) * 60,
        repeat_targets_until_deadline=bool(args.repeat_targets_until_deadline),
        pause_between_targets=max(0.0, float(args.pause_between_targets)),
        min_successful_targets=int(args.min_successful_targets),
        min_interactions=int(args.min_interactions),
        comment_every=max(0, int(args.comment_every)),
        max_comments=max(0, int(args.max_comments)),
        continue_on_target_navigation_error=bool(
            args.continue_on_target_navigation_error
        ),
    )


def browser_options(args: argparse.Namespace) -> CalibrationBrowserOptions:
    templates = tuple(value.strip() for value in args.comment_template if value.strip())
    return CalibrationBrowserOptions(
        timeout_ms=int(args.timeout_ms),
        locate_timeout_ms=max(0, int(args.locate_timeout_ms)),
        wait_after_load=float(args.wait_after_load),
        screenshots=not args.no_screenshots,
        view_seconds=max(0.0, float(args.view_seconds)),
        interaction_dry_run=bool(args.interaction_dry_run),
        comment_templates=templates or ("👍",),
        visit_landing=bool(args.visit_landing),
        landing_view_seconds=max(0.0, float(args.landing_view_seconds)),
        landing_timeout_ms=max(1, int(args.landing_timeout_ms)),
    )


def resolve_run_dir(args: argparse.Namespace) -> Path:
    if args.run_dir.strip():
        return Path(args.run_dir).expanduser().resolve()
    name = datetime.now().strftime("calibration_%Y%m%d_%H%M%S")
    return (Path(args.out).expanduser() / name).resolve()


def public_args(args: argparse.Namespace) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in vars(args).items():
        if key == "offer_identity_json":
            result[key] = "<configured>" if value else None
        else:
            result[key] = str(value) if isinstance(value, Path) else value
    return result


def rate(value: float) -> float:
    return min(1.0, max(0.0, value))
