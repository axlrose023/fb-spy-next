from __future__ import annotations

import argparse
import os
from typing import Any

from .maintenance_options import add_common_paths


def add_run_command(sub: Any) -> None:
    run = sub.add_parser("run", help="Run profile collect/evaluate/calibrate cycles.")
    add_common_paths(run)
    run.add_argument(
        "--profiles-json", default="storage/facebook/orchestrator/profiles.json"
    )
    run.add_argument("--max-parallel", type=int, default=2)
    run.add_argument("--loop", action="store_true")
    run.add_argument("--cycle-sleep", type=float, default=60.0)
    run.add_argument(
        "--profile-rest-minutes",
        type=float,
        default=0.0,
        help=(
            "Minimum rest after a profile finishes collection and optional "
            "calibration. The larger of this value and --cycle-sleep is used."
        ),
    )
    run.add_argument(
        "--recovery-burst-cycles",
        type=int,
        default=3,
        help=(
            "Number of collect/calibrate recovery cycles run without the normal "
            "profile rest before applying backoff."
        ),
    )
    run.add_argument(
        "--recovery-burst-rest-minutes",
        type=float,
        default=0.0,
        help="Delay before the next validation collection inside a recovery burst.",
    )
    run.add_argument(
        "--infrastructure-retry-minutes",
        type=float,
        default=5.0,
        help="Retry delay after Octo, proxy, or calibration infrastructure errors.",
    )
    run.add_argument("--discovery-interval", type=float, default=300.0)
    run.add_argument("--max-cycles", type=int, default=0, help=argparse.SUPPRESS)
    run.add_argument("--collect-minutes", type=float, default=15.0)
    run.add_argument("--collect-timeout-grace", type=float, default=180.0)
    run.add_argument("--collect-scrolls", type=int, default=10000)
    run.add_argument("--resolve-max", type=int, default=200)
    run.add_argument("--scroll-px", type=int, default=520)
    run.add_argument("--max-ads-per-view", type=int, default=1)
    run.add_argument("--landing-archive-timeout", type=float, default=12.0)
    run.add_argument("--landing-archive-max-resources", type=int, default=80)
    run.add_argument("--video-max-seconds", type=float, default=10.0)
    run.add_argument("--no-video-recording", action="store_true")
    run.add_argument("--no-landing-archives", action="store_true")
    run.add_argument(
        "--interest-safe-collection",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Passively scan the feed, classify cards first, and allow active "
            "browser actions only for relevance-gated ads."
        ),
    )
    run.add_argument(
        "--relevant-enrichment",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Capture video and landing artifacts only for prefiltered ads.",
    )
    run.add_argument(
        "--isolated-hold-resolution",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Resolve uncertain passive CTA URLs in a cookie-free context before "
            "allowing any authenticated profile action."
        ),
    )
    run.add_argument("--isolated-resolution-timeout", type=float, default=900.0)
    run.add_argument("--enrichment-timeout", type=float, default=1200.0)
    run.add_argument("--octo-host", default="")
    run.add_argument("--octo-port", type=int, default=0)
    run.add_argument(
        "--octo-headless",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    run.add_argument("--debug", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--calibration-limit", type=int, default=20)
    run.add_argument("--calibration-target-goal", type=int, default=10)
    run.add_argument(
        "--calibration-low-relevance-target-goal",
        type=int,
        default=30,
    )
    run.add_argument(
        "--calibration-recovery-target-goal",
        type=int,
        default=40,
    )
    run.add_argument(
        "--calibration-recovery-target-limit",
        type=int,
        default=50,
    )
    run.add_argument("--calibration-timeout-grace", type=float, default=180.0)
    run.add_argument("--calibration-view-seconds", type=float, default=45.0)
    run.add_argument("--calibration-pause", type=float, default=2.0)
    run.add_argument("--calibration-locate-timeout", type=float, default=12.0)
    run.add_argument("--calibration-page-timeout", type=float, default=45.0)
    run.add_argument(
        "--calibration-visit-landing",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    run.add_argument("--calibration-landing-view-seconds", type=float, default=45.0)
    run.add_argument("--calibration-landing-timeout", type=float, default=20.0)
    run.add_argument(
        "--calibration-offer-funnel",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    run.add_argument(
        "--calibration-direct-offer-fallback",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    run.add_argument("--calibration-session-minutes", type=float, default=15.0)
    run.add_argument(
        "--calibration-repeat-targets-until-deadline",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    run.add_argument("--calibration-funnel-target-goal", type=int, default=3)
    run.add_argument("--calibration-prelander-max-scrolls", type=int, default=12)
    run.add_argument("--calibration-quiz-max-questions", type=int, default=10)
    run.add_argument(
        "--calibration-offer-submit-mode",
        choices=("disabled", "fill_only", "allowlisted"),
        default="disabled",
    )
    run.add_argument(
        "--calibration-offer-submit-allow-domain",
        action="append",
        default=[
            value.strip()
            for value in os.getenv(
                "FACEBOOK_CALIBRATION_OFFER_SUBMIT_ALLOW_DOMAINS",
                "",
            ).split(",")
            if value.strip()
        ],
    )
    run.add_argument(
        "--calibration-offer-identity-json",
        default=os.getenv("FACEBOOK_CALIBRATION_OFFER_IDENTITY_JSON", ""),
    )
    run.add_argument(
        "--calibration-offer-success-wait-seconds", type=float, default=20.0
    )
    run.add_argument("--calibration-max-retained-offer-tabs", type=int, default=6)
    run.add_argument("--min-calibration-targets", type=int, default=2)
    run.add_argument("--calibration-cooldown-hours", type=float, default=1.0)
    run.add_argument(
        "--soft-drop-calibration-windows",
        type=int,
        default=3,
    )
    run.add_argument("--watch-drop-ratio", type=float, default=0.70)
    run.add_argument("--immediate-drop-ratio", type=float, default=0.70)
    run.add_argument(
        "--minimum-healthy-relevant-rate",
        type=float,
        default=0.75,
    )
    run.add_argument(
        "--minimum-healthy-relevant-ads",
        type=int,
        default=15,
    )
    run.add_argument("--zero-ads-windows", type=int, default=2)
    run.add_argument("--absolute-low-ads-windows", type=int, default=2)
    run.add_argument("--absolute-low-ads-per-hour", type=float, default=12.0)
    run.add_argument(
        "--zero-ads-calibration-cooldown-minutes",
        type=float,
        default=30.0,
    )
    run.add_argument("--zero-ads-calibration-burst-limit", type=int, default=8)
    run.add_argument(
        "--zero-ads-calibration-backoff-hours",
        type=float,
        default=2.0,
    )
    run.add_argument("--calibration-retry-cooldown-hours", type=float, default=0.5)
    run.add_argument(
        "--maintenance-calibration-hours",
        type=float,
        default=6.0,
    )
    run.add_argument(
        "--maintenance-min-valid-windows",
        type=int,
        default=3,
    )
    run.add_argument("--max-calibrations-per-24h", type=int, default=24)
    run.add_argument("--calibration-reaction-rate", type=float, default=0.65)
    run.add_argument("--calibration-follow-rate", type=float, default=0.20)
    run.add_argument("--calibration-comment-every", type=int, default=0)
    run.add_argument("--calibration-max-reactions", type=int, default=6)
    run.add_argument("--calibration-max-follows", type=int, default=2)
    run.add_argument("--calibration-max-comments", type=int, default=0)
    run.add_argument("--calibration-min-interactions", type=int, default=1)
    run.add_argument("--calibration-comment-template", action="append", default=[])
    run.add_argument(
        "--classify-relevance",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    run.add_argument("--relevance-timeout", type=float, default=900.0)
    run.add_argument(
        "--import-backend",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Import each completed classified run into the application database.",
    )
    run.add_argument("--backend-import-timeout", type=float, default=300.0)
    run.add_argument("--discover-octo-profiles", action="store_true")
    run.add_argument("--octo-api-token", default="")
    run.add_argument("--octo-search-tags", default="")
    run.add_argument("--enable-discovered", action="store_true")
