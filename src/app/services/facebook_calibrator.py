"""Calibrate one profile using previously classified relevant ads.

The calibrator never discovers or classifies ads. It reopens saved Facebook
posts when available and can continue through their saved relevant offer in the
same Octo context. Every attempted action is written to private audit artifacts.
"""

from __future__ import annotations

import argparse
import random
import signal
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright

from app.facebook.calibration import (
    EngagementPolicy,
    click_like,
    follow_advertiser,
    locate_saved_post,
    plan_engagement,
    post_comment,
    view_feed_ad,
    visit_ad_landing,
    wait_for_saved_post,
)
from app.services import facebook_runner
from app.services.facebook.calibration import (
    CalibrationTarget,
    append_event,
    load_saved_facebook_targets_from_ads_json,
    quarantined_facebook_post_urls,
    record_facebook_post_target_result,
    rotate_calibration_targets,
    write_json,
    write_targets,
)
from app.services.facebook.offer_funnel import (
    OfferFunnelPolicy,
    OfferFunnelSession,
    load_offer_identity,
    offer_url,
    public_offer_target,
    redact_error,
    redact_url,
)
from app.settings import get_config

STOP_REQUESTED = False
TRANSIENT_NAVIGATION_ERRORS = (
    "ERR_SOCKS_CONNECTION_FAILED",
    "ERR_PROXY_CONNECTION_FAILED",
    "ERR_NETWORK_CHANGED",
    "ERR_CONNECTION_RESET",
    "ERR_CONNECTION_CLOSED",
    "ERR_TIMED_OUT",
)
BROWSER_CONTEXT_CLOSED_ERRORS = (
    "Target page, context or browser has been closed",
    "BrowserContext.new_page: Target page, context or browser has been closed",
)


class SavedPostAccessError(RuntimeError):
    """The profile or its proxy blocked direct access to a saved post."""


def _request_stop(signum, _frame) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True
    raise KeyboardInterrupt(f"signal {signum}")


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    _validate_args(args, parser)

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    config = get_config()
    profile_uuid = args.octo_profile_uuid or config.facebook.octo_profile_uuid
    facebook_runner.OCTO_API = f"http://{args.octo_host}:{args.octo_port}"
    facebook_runner.OCTO_PROFILE_UUID = profile_uuid
    facebook_runner.OCTO_HEADLESS = args.octo_headless

    run_dir = _resolve_run_dir(args)
    run_dir.mkdir(parents=True, exist_ok=True)
    events_path = run_dir / "events.jsonl"
    results_path = run_dir / "results.json"
    summary_path = run_dir / "summary.json"

    results: list[dict] = []
    engagement_results: list[dict] = []
    funnel_summary: dict = {}
    try:
        ws_endpoint = ""
        connection_data = {}
        profile_country = None
        if _should_connect_before_targets(args):
            ws_endpoint, connection_data = facebook_runner.get_cdp_endpoint()
            ws_endpoint = facebook_runner.rewrite_cdp_endpoint_host(
                ws_endpoint,
                args.octo_host,
            )
            profile_country = facebook_runner.normalize_country(
                connection_data.get("country")
            )
        selected_country = (
            None if args.no_country_filter else (args.country or profile_country)
        )

        meta = {
            "mode": "calibration",
            "started_at": facebook_runner.utc_now(),
            "run_dir": str(run_dir),
            "octo_profile_uuid": profile_uuid,
            "octo_host": args.octo_host,
            "octo_port": args.octo_port,
            "octo_ip": connection_data.get("ip"),
            "profile_country": profile_country,
            "selected_country": selected_country,
            "source": "ads_json" if args.ads_json else "db",
            "args": _public_args(args),
            "connection_data": connection_data,
        }
        write_json(run_dir / "run_meta.json", meta)
        append_event(
            events_path, {"at": facebook_runner.utc_now(), "kind": "started", **meta}
        )

        targets = _load_saved_targets(args, selected_country)
        write_targets(run_dir / "targets.json", targets)
        write_targets(run_dir / "engagement_targets.json", targets)
        print(
            f"[calibration] targets={len(targets)} country={selected_country or 'all'} "
            f"profile={profile_uuid} run_dir={run_dir}",
            flush=True,
        )

        if not targets:
            summary = {
                "status": "no_direct_facebook_targets",
                "finished_at": facebook_runner.utc_now(),
                "targets": 0,
                "ok": 0,
                "failed": 0,
            }
            write_json(summary_path, summary)
            append_event(
                events_path,
                {"at": facebook_runner.utc_now(), "kind": "finished", **summary},
            )
            return 1

        if args.dry_run:
            summary = {
                "status": "dry_run",
                "finished_at": facebook_runner.utc_now(),
                "targets": len(targets),
                "ok": 0,
                "failed": 0,
            }
            write_json(summary_path, summary)
            append_event(
                events_path,
                {"at": facebook_runner.utc_now(), "kind": "finished", **summary},
            )
            return 0

        offer_identity = None
        if args.offer_funnel:
            offer_identity = load_offer_identity(
                args.offer_identity_json,
                profile_uuid=profile_uuid,
                country=selected_country,
            )
            if args.offer_submit_mode == "allowlisted" and not offer_identity.complete:
                raise ValueError(
                    "The selected offer identity must include a first name, valid "
                    "email and phone before allowlisted submission is enabled"
                )

        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(ws_endpoint)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            policy = _engagement_policy(args)
            funnel_session = (
                OfferFunnelSession(
                    context,
                    policy=_offer_funnel_policy(args),
                    identity=offer_identity,
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
            deadline = (
                time.monotonic() + args.session_minutes * 60
                if args.session_minutes > 0
                else None
            )
            repeat_targets = bool(
                args.repeat_targets_until_deadline and deadline is not None
            )
            attempt_index = 0
            try:
                while True:
                    if STOP_REQUESTED or (deadline is not None and time.monotonic() >= deadline):
                        break
                    if attempt_index >= len(targets) and not repeat_targets:
                        break
                    target = targets[attempt_index % len(targets)]
                    attempt_index += 1
                    result = _calibrate_saved_ad(
                        context,
                        target,
                        attempt_index,
                        len(targets),
                        run_dir,
                        events_path,
                        policy,
                        budget,
                        args,
                        funnel_session=funnel_session,
                    )
                    results.append(result)
                    write_json(results_path, results)
                    write_json(run_dir / "engagement_results.json", results)
                    record_facebook_post_target_result(
                        args.target_health_json,
                        result,
                    )
                    if _should_stop_after_target_result(result, args):
                        break
                    if not repeat_targets and _calibration_goals_met(
                        results,
                        args,
                        targets_available=len(targets),
                    ):
                        break
                    if args.pause_between_targets > 0:
                        if deadline is None or time.monotonic() < deadline:
                            time.sleep(args.pause_between_targets)
                engagement_results = results
            finally:
                if funnel_session is not None:
                    funnel_summary = funnel_session.summary()
                    funnel_session.close()

        ok = sum(1 for result in results if result.get("ok"))
        failed = len(results) - ok
        interaction_counts = _interaction_counts(engagement_results)
        target_goal_met = (
            ok >= args.min_successful_targets
            if args.min_successful_targets > 0
            else failed == 0
        )
        interaction_goal_met = interaction_counts["successful"] >= args.min_interactions
        infrastructure_error = next(
            (
                result.get("error")
                for result in results
                if result.get("infrastructure_error")
            ),
            None,
        )
        summary = {
            "status": (
                "interrupted"
                if STOP_REQUESTED
                else "infrastructure_error"
                if infrastructure_error
                else "completed"
            ),
            "finished_at": facebook_runner.utc_now(),
            "targets": len(targets),
            "visited": len(results),
            "ok": ok,
            "failed": failed,
            "target_goal_met": target_goal_met,
            "interaction_goal_met": interaction_goal_met,
            "interactions": interaction_counts,
            "offer_funnel": funnel_summary,
            "results_path": str(results_path),
            "targets_path": str(run_dir / "targets.json"),
            "engagement_results_path": str(run_dir / "engagement_results.json"),
        }
        if infrastructure_error:
            summary["infrastructure_error"] = infrastructure_error
        write_json(summary_path, summary)
        append_event(
            events_path,
            {"at": facebook_runner.utc_now(), "kind": "finished", **summary},
        )
        print(
            f"[calibration done] visited={len(results)} ok={ok} failed={failed} "
            f"interactions={interaction_counts['successful']} "
            f"active={interaction_counts['already_active']} "
            f"satisfied={interaction_counts['satisfied']}",
            flush=True,
        )
        return (
            0
            if not infrastructure_error and target_goal_met and interaction_goal_met
            else 2
        )
    except KeyboardInterrupt:
        summary = {
            "status": "interrupted",
            "finished_at": facebook_runner.utc_now(),
            "visited": len(results),
        }
        write_json(summary_path, summary)
        append_event(
            events_path, {"at": facebook_runner.utc_now(), "kind": "interrupted"}
        )
        return 130
    except Exception as exc:
        summary = {
            "status": "failed",
            "finished_at": facebook_runner.utc_now(),
            "error": redact_error(exc),
            "traceback": redact_error(traceback.format_exc()),
            "visited": len(results),
        }
        write_json(summary_path, summary)
        append_event(
            events_path, {"at": facebook_runner.utc_now(), "kind": "failed", **summary}
        )
        print(f"[calibration error] {exc!r}", file=sys.stderr, flush=True)
        return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--octo-host", default="127.0.0.1")
    parser.add_argument("--octo-port", type=int, default=58888)
    parser.add_argument("--octo-profile-uuid", default="")
    parser.add_argument("--octo-headless", action="store_true")
    parser.add_argument(
        "--country",
        default="",
        help="Target ad country. Defaults to Octo profile country.",
    )
    parser.add_argument("--no-country-filter", action="store_true")
    parser.add_argument("--ads-json", action="append", type=Path, default=[])
    parser.add_argument("--target-health-json", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--target-offset", type=int, default=0)
    parser.add_argument("--view-seconds", type=float, default=45.0)
    parser.add_argument("--wait-after-load", type=float, default=3.0)
    parser.add_argument("--locate-timeout-ms", type=int, default=12_000)
    parser.add_argument("--pause-between-targets", type=float, default=2.0)
    parser.add_argument("--timeout-ms", type=int, default=45000)
    parser.add_argument(
        "--visit-landing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Open the saved ad CTA in the same Octo browser context.",
    )
    parser.add_argument("--landing-view-seconds", type=float, default=12.0)
    parser.add_argument("--landing-timeout-ms", type=int, default=20_000)
    parser.add_argument(
        "--offer-funnel",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Browse the relevant prelander/offer instead of a passive landing visit.",
    )
    parser.add_argument(
        "--direct-offer-fallback",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use the saved full offer URL when a Facebook post or CTA is unavailable.",
    )
    parser.add_argument("--session-minutes", type=float, default=0.0)
    parser.add_argument(
        "--repeat-targets-until-deadline",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument("--prelander-max-scrolls", type=int, default=12)
    parser.add_argument("--quiz-max-questions", type=int, default=10)
    parser.add_argument(
        "--offer-submit-mode",
        choices=("disabled", "fill_only", "allowlisted"),
        default="disabled",
    )
    parser.add_argument("--offer-submit-allow-domain", action="append", default=[])
    parser.add_argument("--offer-identity-json", type=Path, default=None)
    parser.add_argument("--offer-success-wait-seconds", type=float, default=20.0)
    parser.add_argument("--max-retained-offer-tabs", type=int, default=6)
    parser.add_argument("--reaction-rate", type=float, default=0.65)
    parser.add_argument("--follow-rate", type=float, default=0.20)
    parser.add_argument(
        "--comment-every",
        type=int,
        default=0,
        help="Post a comment on every Nth successfully opened saved ad; 0 disables comments.",
    )
    parser.add_argument("--max-reactions", type=int, default=6)
    parser.add_argument("--max-follows", type=int, default=2)
    parser.add_argument("--max-comments", type=int, default=0)
    parser.add_argument("--min-interactions", type=int, default=1)
    parser.add_argument(
        "--continue-on-target-navigation-error",
        action="store_true",
        help=(
            "Continue a manual batch after one saved post exhausts transient "
            "navigation retries. Browser-context failures still stop the batch."
        ),
    )
    parser.add_argument(
        "--min-successful-targets",
        type=int,
        default=0,
        help="Minimum successfully opened saved Facebook posts; 0 requires every target.",
    )
    parser.add_argument("--comment-template", action="append", default=[])
    parser.add_argument("--interaction-dry-run", action="store_true")
    parser.add_argument("--out", default="storage/facebook/calibration")
    parser.add_argument(
        "--run-dir", default="", help="Exact output directory. Overrides --out."
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-screenshots", action="store_true")
    return parser


def _validate_args(args, parser: argparse.ArgumentParser) -> None:
    nonnegative = (
        "session_minutes",
        "landing_view_seconds",
        "offer_success_wait_seconds",
    )
    for name in nonnegative:
        if float(getattr(args, name)) < 0:
            parser.error(f"--{name.replace('_', '-')} cannot be negative")
    if args.prelander_max_scrolls < 0:
        parser.error("--prelander-max-scrolls cannot be negative")
    if args.quiz_max_questions < 0:
        parser.error("--quiz-max-questions cannot be negative")
    if args.max_retained_offer_tabs < 1:
        parser.error("--max-retained-offer-tabs must be at least 1")
    if args.offer_submit_mode == "allowlisted":
        if not args.offer_submit_allow_domain:
            parser.error(
                "--offer-submit-mode=allowlisted requires at least one "
                "--offer-submit-allow-domain"
            )
        if args.offer_identity_json is None:
            parser.error(
                "--offer-submit-mode=allowlisted requires --offer-identity-json"
            )


def _should_connect_before_targets(args) -> bool:
    if not args.dry_run:
        return True
    return not (args.country or args.no_country_filter)


def _load_saved_targets(args, selected_country: str | None) -> list[CalibrationTarget]:
    if not args.ads_json:
        return []
    targets = load_saved_facebook_targets_from_ads_json(
        args.ads_json,
        country=selected_country,
        limit=1000,
        include_direct_offers=bool(
            getattr(args, "offer_funnel", False)
            and getattr(args, "direct_offer_fallback", True)
        ),
        excluded_urls=quarantined_facebook_post_urls(args.target_health_json),
    )
    return rotate_calibration_targets(
        targets,
        args.target_offset,
    )[: max(0, args.limit)]


def _engagement_policy(args) -> EngagementPolicy:
    return EngagementPolicy(
        reaction_rate=_rate(args.reaction_rate),
        follow_rate=_rate(args.follow_rate),
        comment_every=max(0, args.comment_every),
        max_reactions=max(0, args.max_reactions),
        max_follows=max(0, args.max_follows),
        max_comments=max(0, args.max_comments),
        min_interactions=max(0, args.min_interactions),
    )


def _offer_funnel_policy(args) -> OfferFunnelPolicy:
    return OfferFunnelPolicy(
        enabled=bool(getattr(args, "offer_funnel", False)),
        direct_offer_fallback=bool(
            getattr(args, "direct_offer_fallback", True)
        ),
        browse_seconds=max(0.0, float(args.landing_view_seconds)),
        max_scrolls=max(0, int(args.prelander_max_scrolls)),
        quiz_max_questions=max(0, int(args.quiz_max_questions)),
        submit_mode=str(args.offer_submit_mode),
        submit_allow_domains=tuple(args.offer_submit_allow_domain),
        success_wait_seconds=max(0.0, float(args.offer_success_wait_seconds)),
        max_retained_tabs=max(1, int(args.max_retained_offer_tabs)),
        navigation_timeout_ms=max(1, int(args.landing_timeout_ms)),
    )


def _calibrate_saved_ad(
    context,
    target: CalibrationTarget,
    index: int,
    total: int,
    run_dir: Path,
    events_path: Path,
    policy: EngagementPolicy,
    budget: dict[str, int],
    args,
    *,
    funnel_session: OfferFunnelSession | None = None,
) -> dict:
    started = time.monotonic()
    post_url = target.facebook_post_url or ""
    result = {
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
    append_event(
        events_path,
        {
            "at": facebook_runner.utc_now(),
            "kind": "saved_ad_started",
            "index": index,
            "total": total,
            "target": public_offer_target(target),
        },
    )
    page: Page | None = None
    skip_page_close = False
    try:
        if not post_url:
            if funnel_session is None:
                raise RuntimeError("calibration target has no direct Facebook post")
            engagement = _direct_offer_engagement(
                funnel_session,
                target,
                budget,
                view_status="post_unavailable",
            )
            action = engagement["actions"][0]
            result.update(engagement)
            result["ok"] = _offer_funnel_action_ok(action)
            if result["ok"]:
                budget["successful"] += 1
            else:
                result["error"] = f"direct offer fallback failed: {action}"
            result["duration_seconds"] = round(time.monotonic() - started, 3)
            append_event(
                events_path,
                {
                    "at": facebook_runner.utc_now(),
                    "kind": "saved_ad_finished" if result["ok"] else "saved_ad_failed",
                    **result,
                },
            )
            return result

        page = context.new_page()
        try:
            response = _goto_saved_post(
                page,
                post_url,
                timeout_ms=args.timeout_ms,
            )
            result["status"] = response.status if response else None
            result["final_url"] = redact_url(page.url)
            if response and response.status in {401, 403}:
                try:
                    page_title = page.title().strip()
                except PlaywrightError:
                    page_title = ""
                detail = f" ({page_title})" if page_title else ""
                raise SavedPostAccessError(
                    f"saved Facebook post access blocked: HTTP {response.status}{detail}"
                )
            if response and response.status >= 400:
                raise RuntimeError(
                    f"saved Facebook post returned HTTP {response.status}"
                )
        except SavedPostAccessError as exc:
            if funnel_session is None or not offer_url(target):
                raise
            result["source"] = "direct_offer_fallback"
            result["facebook_post_status"] = "access_blocked"
            result["facebook_post_error"] = str(exc)
            engagement = _direct_offer_engagement(
                funnel_session,
                target,
                budget,
                view_status="post_access_blocked",
            )
            result.update(engagement)
            action = engagement["actions"][0]
            result["ok"] = _offer_funnel_action_ok(action)
            if result["ok"]:
                budget["successful"] += 1
            else:
                result["error"] = f"direct offer fallback failed: {action}"
            result["duration_seconds"] = round(time.monotonic() - started, 3)
            append_event(
                events_path,
                {
                    "at": facebook_runner.utc_now(),
                    "kind": (
                        "saved_ad_finished" if result["ok"] else "saved_ad_failed"
                    ),
                    **result,
                },
            )
            return result
        if args.wait_after_load > 0:
            page.wait_for_timeout(round(args.wait_after_load * 1000))

        located = wait_for_saved_post(
            page,
            target,
            timeout_ms=max(0, args.locate_timeout_ms),
        )
        result["match"] = located
        if located.get("status") != "located":
            if funnel_session is None:
                raise RuntimeError(f"saved Facebook post not found: {located}")
            budget["opened"] = budget.get("opened", 0) + 1
            action = funnel_session.run(target)
            engagement = {
                "view": {"status": "post_not_found", "match": located},
                "actions": [action],
                "relevant_ad_number": budget["opened"],
            }
        else:
            element_id = str(located["element_id"])
            if not args.no_screenshots:
                try:
                    screenshot = (
                        run_dir
                        / "screens"
                        / f"{index:04d}_{_safe_slug(target.advertiser or 'saved_ad')}.png"
                    )
                    screenshot.parent.mkdir(parents=True, exist_ok=True)
                    page.locator(f'[data-fbspy-id="{element_id}"]').first.screenshot(
                        path=str(screenshot),
                        timeout=8000,
                    )
                    result["screenshot"] = str(screenshot.relative_to(run_dir))
                except Exception as exc:
                    result["screenshot_error"] = redact_error(exc)

            budget["opened"] = budget.get("opened", 0) + 1
            engagement = _engage_row(
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
                policy,
                budget,
                args,
                relevant_ad_number=budget["opened"],
                view_seconds=max(0.0, args.view_seconds),
                funnel_session=funnel_session,
            )
        result.update(engagement)
        funnel_ok = any(
            action.get("action") == "offer_funnel"
            and _offer_funnel_action_ok(action)
            for action in engagement.get("actions", [])
        )
        post_viewed = engagement.get("view", {}).get("status") == "viewing"
        result["ok"] = _calibration_target_ok(
            post_viewed=post_viewed,
            funnel_ok=funnel_ok,
            funnel_required=(
                funnel_session is not None
                and bool(getattr(args, "visit_landing", False))
            ),
            post_required=located.get("status") == "located",
        )
        if funnel_ok and engagement.get("view", {}).get("status") != "viewing":
            budget["successful"] += 1
        if not result["ok"]:
            result["error"] = (
                f"saved Facebook post view failed: {engagement.get('view')}"
            )
        result["duration_seconds"] = round(time.monotonic() - started, 3)
        append_event(
            events_path,
            {
                "at": facebook_runner.utc_now(),
                "kind": "saved_ad_finished" if result["ok"] else "saved_ad_failed",
                **result,
            },
        )
    except Exception as exc:
        result["error"] = redact_error(exc)
        transient_navigation_error = _is_transient_navigation_error(exc)
        browser_context_closed = _is_browser_context_closed_error(exc)
        if transient_navigation_error:
            result["transient_navigation_error"] = True
        if browser_context_closed:
            result["browser_context_closed"] = True
        if (
            isinstance(exc, SavedPostAccessError)
            or transient_navigation_error
            or browser_context_closed
        ):
            result["infrastructure_error"] = True
            skip_page_close = True
        result["duration_seconds"] = round(time.monotonic() - started, 3)
        append_event(
            events_path,
            {
                "at": facebook_runner.utc_now(),
                "kind": "saved_ad_failed",
                **result,
            },
        )
    finally:
        # A broken proxy can leave Playwright waiting forever while closing the
        # failed target. The profile guard stops the whole Octo browser after
        # this process exits, so leave that one page for Octo to clean up.
        if page is not None and not skip_page_close:
            try:
                page.close(run_before_unload=False)
            except PlaywrightError:
                pass
    return result


def _should_stop_after_target_result(result: dict, args) -> bool:
    if not result.get("infrastructure_error"):
        return False
    return not (
        bool(getattr(args, "continue_on_target_navigation_error", False))
        and result.get("transient_navigation_error") is True
        and result.get("browser_context_closed") is not True
    )


def _goto_saved_post(page: Page, url: str, *, timeout_ms: int, attempts: int = 3):
    ignored_proxy_certificate_error = False
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
        except PlaywrightError as exc:
            if (
                not ignored_proxy_certificate_error
                and facebook_runner.PROXY_CERTIFICATE_AUTHORITY_ERROR in str(exc)
                and facebook_runner._ignore_proxy_certificate_errors(page)
            ):
                ignored_proxy_certificate_error = True
                continue
            transient = any(code in str(exc) for code in TRANSIENT_NAVIGATION_ERRORS)
            if not transient or attempt >= attempts:
                raise
            page.wait_for_timeout(1500 * attempt)
    raise RuntimeError("saved Facebook post navigation exhausted retries")


def _is_transient_navigation_error(exc: Exception) -> bool:
    return any(code in str(exc) for code in TRANSIENT_NAVIGATION_ERRORS)


def _is_browser_context_closed_error(exc: Exception) -> bool:
    return any(message in str(exc) for message in BROWSER_CONTEXT_CLOSED_ERRORS)


def _calibration_goals_met(
    results: list[dict],
    args,
    *,
    targets_available: int | None = None,
) -> bool:
    if args.min_successful_targets <= 0:
        return False
    required_opened = args.min_successful_targets
    comment_every = max(0, int(getattr(args, "comment_every", 0)))
    comments_enabled = int(getattr(args, "max_comments", 0)) > 0
    if (
        comments_enabled
        and comment_every > 0
        and targets_available is not None
        and targets_available >= comment_every
    ):
        required_opened = max(required_opened, comment_every)
    if sum(1 for result in results if result.get("ok")) < required_opened:
        return False
    return _interaction_counts(results)["successful"] >= args.min_interactions


def _engage_row(
    page: Page,
    row: dict,
    target: CalibrationTarget,
    policy: EngagementPolicy,
    budget: dict[str, int],
    args,
    *,
    relevant_ad_number: int,
    view_seconds: float | None = None,
    funnel_session: OfferFunnelSession | None = None,
) -> dict:
    element_id = str(row.get("element_id") or "")
    result = {
        "advertiser": str(row.get("advertiser") or ""),
        "displayed_domain": str(row.get("domain") or ""),
        "headline": str(row.get("headline") or ""),
        "element_id": element_id,
        "source": "saved_facebook_post",
        "relevant_ad_number": relevant_ad_number,
        "target_fb_ad_id": target.fb_ad_id,
        "view": _safe_action(
            "view",
            view_feed_ad,
            page,
            element_id,
            max(
                0.0,
                args.view_seconds if view_seconds is None else view_seconds,
            ),
        ),
        "actions": [],
    }

    comment_templates = [
        value.strip() for value in args.comment_template if value.strip()
    ] or ["👍"]
    engagement = plan_engagement(
        policy,
        budget,
        relevant_ad_number=relevant_ad_number,
        comments_available=bool(comment_templates),
        visit_landing=bool(getattr(args, "visit_landing", False)),
        random_value=random.random,
    )

    if args.interaction_dry_run:
        result["actions"] = [
            {"action": action, "status": "dry_run"}
            for action in engagement.due_actions()
        ]
        return result

    if engagement.reaction:
        budget["reaction"] += 1
        action = _engage_reaction(page, row, element_id, target)
        result["actions"].append(action)
        if action.get("status") == "clicked":
            budget["successful"] += 1

    if engagement.comment:
        budget["comment"] += 1
        refreshed_row = _refresh_engagement_row(page, row, target)
        comment_element_id = str((refreshed_row or row).get("element_id") or element_id)
        template = comment_templates[0]
        action = _safe_action(
            "comment",
            post_comment,
            page,
            comment_element_id,
            template,
        )
        result["actions"].append(action)
        if action.get("status") == "posted":
            budget["successful"] += 1

    if engagement.follow:
        budget["follow"] += 1
        refreshed_row = _refresh_engagement_row(page, row, target)
        follow_element_id = str((refreshed_row or row).get("element_id") or element_id)
        action = _safe_action(
            "follow",
            follow_advertiser,
            page,
            follow_element_id,
            str(row.get("advertiser") or ""),
            timeout_ms=args.timeout_ms,
        )
        result["actions"].append(action)
        if action.get("status") == "clicked":
            budget["successful"] += 1

    if engagement.landing_visit:
        budget["landing_visit"] = budget.get("landing_visit", 0) + 1
        refreshed_row = _refresh_engagement_row(page, row, target)
        landing_element_id = str(
            (refreshed_row or row).get("element_id") or element_id
        )
        expected_url = target.landing_clean or (
            f"https://{target.displayed_domain}"
            if target.displayed_domain
            else ""
        )
        if funnel_session is not None:
            action = _safe_action(
                "offer_funnel",
                funnel_session.run,
                target,
                source_page=page,
                element_id=landing_element_id,
            )
        else:
            action = _safe_action(
                "landing_visit",
                visit_ad_landing,
                page,
                landing_element_id,
                cta=target.cta,
                expected_url=expected_url,
                dwell_seconds=max(
                    0.0,
                    float(getattr(args, "landing_view_seconds", 0.0)),
                ),
                timeout_ms=max(
                    1,
                    int(getattr(args, "landing_timeout_ms", args.timeout_ms)),
                ),
            )
        result["actions"].append(action)
        if action.get("status") == "visited" or _offer_funnel_action_ok(action):
            budget["successful"] += 1
    return result


def _direct_offer_engagement(
    funnel_session: OfferFunnelSession,
    target: CalibrationTarget,
    budget: dict[str, int],
    *,
    view_status: str,
) -> dict:
    budget["opened"] = budget.get("opened", 0) + 1
    action = funnel_session.run(target)
    return {
        "view": {"status": view_status},
        "actions": [action],
        "relevant_ad_number": budget["opened"],
    }


def _engage_reaction(
    page: Page,
    row: dict,
    element_id: str,
    target: CalibrationTarget,
) -> dict:
    attempts: list[dict] = []
    current_element_id = element_id
    for _ in range(3):
        action = _safe_action("reaction", click_like, page, current_element_id)
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
        refreshed = _refresh_engagement_row(page, row, target)
        if refreshed is None or not refreshed.get("element_id"):
            action["attempts"] = attempts[:-1]
            return action
        current_element_id = str(refreshed["element_id"])

    final = attempts[-1]
    final["attempts"] = attempts[:-1]
    return final


def _refresh_engagement_row(
    page: Page,
    original: dict,
    target: CalibrationTarget,
) -> dict | None:
    try:
        located = locate_saved_post(page, target)
    except Exception:
        return None
    if located.get("status") != "located":
        return None
    return {**original, "element_id": str(located["element_id"])}


def _safe_action(name: str, function, *args, **kwargs) -> dict:
    try:
        return {"action": name, **function(*args, **kwargs)}
    except Exception as exc:
        return {"action": name, "status": "failed", "error": redact_error(exc)}


def _offer_funnel_action_ok(action: dict) -> bool:
    return action.get("action") == "offer_funnel" and action.get("status") in {
        "landing_opened",
        "offer_engaged",
        "form_ready",
        "form_submitted_unconfirmed",
        "success_confirmed",
        "unsafe_form_blocked",
    }


def _calibration_target_ok(
    *,
    post_viewed: bool,
    funnel_ok: bool,
    funnel_required: bool,
    post_required: bool,
) -> bool:
    if funnel_required:
        return funnel_ok and (post_viewed or not post_required)
    return post_viewed or funnel_ok


def _interaction_counts(results: list[dict]) -> dict[str, int]:
    opened = sum(
        1
        for result in results
        if result.get("view", {}).get("status") == "viewing"
        or ("view" not in result and result.get("ok"))
    )
    counts = {
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
    success_status = {
        "reaction": "clicked",
        "comment": "posted",
        "follow": "clicked",
        "landing_visit": "visited",
    }
    for result in results:
        for action in result.get("actions", []):
            name = str(action.get("action") or "")
            status = str(action.get("status") or "")
            if name == "offer_funnel":
                form_status = str(action.get("form_status") or "")
                if action.get("opening") == "direct_offer":
                    counts["direct_offer_fallback_attempts"] += 1
                if action.get("form_detected"):
                    counts["funnel_forms_detected"] += 1
                if action.get("form_submitted"):
                    counts["funnel_submit_attempted"] += 1
                if form_status in {
                    "identity_missing",
                    "invalid_submit_mode",
                    "repeat_submit_blocked",
                    "required_contact_fields_not_filled",
                    "submit_control_not_found",
                    "submit_domain_not_allowed",
                }:
                    counts["funnel_submit_blocked"] += 1
                if status == "unsafe_form_blocked":
                    counts["funnel_unsafe_form_blocked"] += 1
                if status == "redirected_without_offer_signals":
                    counts["funnel_stale_redirects"] += 1
                if status == "landing_viewed":
                    counts["funnel_landing_only"] += 1
                if status in {
                    "direct_navigation_failed",
                    "missing_direct_offer_url",
                    "redirected_without_offer_signals",
                }:
                    counts["funnel_unusable_offers"] += 1
                if _offer_funnel_action_ok(action):
                    counts["offer_funnel"] += 1
                    counts["successful"] += 1
                    counts["satisfied"] += 1
                    if status == "success_confirmed":
                        counts["funnel_success_confirmed"] += 1
                    elif status == "form_ready":
                        counts["funnel_form_ready"] += 1
                    else:
                        counts["funnel_offer_engaged"] += 1
                    if action.get("opening") == "direct_offer":
                        counts["direct_offer_fallback"] += 1
                elif status != "dry_run":
                    counts["failed"] += 1
                continue
            if status == "already_active":
                counts["already_active"] += 1
                counts["satisfied"] += 1
            elif success_status.get(name) == status:
                counts[name] += 1
                counts["successful"] += 1
                counts["satisfied"] += 1
            elif status != "dry_run":
                counts["failed"] += 1
    return counts


def _rate(value: float) -> float:
    return min(1.0, max(0.0, value))


def _resolve_run_dir(args) -> Path:
    if args.run_dir.strip():
        return Path(args.run_dir).expanduser().resolve()
    name = datetime.now().strftime("calibration_%Y%m%d_%H%M%S")
    return (Path(args.out).expanduser() / name).resolve()


def _public_args(args) -> dict:
    result = {}
    for key, value in vars(args).items():
        if key == "offer_identity_json":
            result[key] = "<configured>" if value else None
        else:
            result[key] = str(value) if isinstance(value, Path) else value
    return result


def _safe_slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value)
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return (cleaned or "target")[:40]


if __name__ == "__main__":
    raise SystemExit(main())
