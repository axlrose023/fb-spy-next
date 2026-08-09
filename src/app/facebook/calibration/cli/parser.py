from __future__ import annotations

import argparse
from pathlib import Path

DESCRIPTION = """Calibrate one profile using previously classified relevant ads.

The calibrator never discovers or classifies ads. It reopens saved Facebook
posts when available and can continue through their saved relevant offer in the
same Octo context. Every attempted action is written to private audit artifacts.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
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
        help=(
            "Post a comment on every Nth successfully opened saved ad; "
            "0 disables comments."
        ),
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
        help=(
            "Minimum successfully opened saved Facebook posts; 0 requires every target."
        ),
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


def validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    for name in (
        "session_minutes",
        "landing_view_seconds",
        "offer_success_wait_seconds",
    ):
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
