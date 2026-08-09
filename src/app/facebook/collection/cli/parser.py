from __future__ import annotations

import argparse

DESCRIPTION = """Facebook ad-spy runner (standalone, single file).

Connects to a RUNNING Octo Browser profile over CDP and harvests the sponsored
posts shown in that account's mobile Facebook feed. Ad detection is
LANGUAGE-INDEPENDENT (no word lists, no OCR): Facebook marks every sponsored
post's secondary line with private-use-area icon glyphs (U+F17E1 / U+F078B).
We key off those glyphs, which are identical in every locale.

Collected data is written before any click, so a fragile click can never lose
it:
  - For every ad we read (no interaction): advertiser, displayed domain,
    headline, ad text, CTA, creative image, screenshot, destination type, and
    whether the creative contains video. The feed is auto-refreshed (Home)
    when it bottoms out.
  - For link-type ads we then click the CTA inline, wait for the landing tab
    to settle (slow proxies!), capture the FULL url with all utm / fbclid /
    ad-id params, and close the tab. In-FB destinations (video/lead form) open
    no external tab and are skipped without breaking the run.

Ad detection is language-independent: no "Sponsored" word list, no OCR, no
hardcoded CDN paths — only the sponsored glyphs and structural cues.

Prereqs: the Octo profile must already be STARTED. The runner restarts it with
a debug port if needed, then talks to it via Playwright connect_over_cdp.

Usage:
    python fb_spy/runner.py --minutes 10 --out fb_spy/results
    python fb_spy/runner.py --minutes 5 --no-resolve          # collect only
    python fb_spy/runner.py --collect-scrolls 200 --resolve-max 80
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--minutes",
        type=float,
        default=10.0,
        help="Collection budget in minutes (default 10).",
    )
    parser.add_argument(
        "--collect-scrolls", type=int, default=10000, help="Hard cap on feed scrolls."
    )
    parser.add_argument(
        "--resolve-max",
        type=int,
        default=200,
        help="Max link-ads to click-resolve for the full URL.",
    )
    parser.add_argument(
        "--scroll-px",
        type=int,
        default=520,
        help="Mouse-wheel pixels per feed step; lower means more overlap (default 520).",
    )
    parser.add_argument(
        "--max-ads-per-view",
        type=int,
        default=1,
        help="Max newly captured ads to process before scrolling again (default 1).",
    )
    parser.add_argument(
        "--no-resolve",
        action="store_true",
        help="Collect only, never click (no full landing URLs).",
    )
    parser.add_argument(
        "--passive-collect",
        action="store_true",
        help=(
            "Interest-safe scan: never click CTAs/comments or start videos. "
            "Relevant ads can be enriched in a separate post-classification step."
        ),
    )
    parser.add_argument(
        "--no-shots", action="store_true", help="Skip per-ad screenshots."
    )
    parser.add_argument(
        "--no-video-recording",
        action="store_true",
        help="Do not record detected video creatives.",
    )
    parser.add_argument(
        "--video-max-seconds",
        type=float,
        default=30.0,
        help="Maximum seconds to record per video creative (hard-capped at 45).",
    )
    parser.add_argument(
        "--video-fps",
        type=int,
        default=8,
        help="Frame rate for recorded video creatives (default 8).",
    )
    parser.add_argument(
        "--no-landing-archives",
        action="store_true",
        help="Do not save zip archives of resolved landing pages.",
    )
    parser.add_argument(
        "--landing-archive-timeout",
        type=float,
        default=20.0,
        help="HTTP timeout for landing archive fetches (default 20s).",
    )
    parser.add_argument(
        "--landing-archive-max-resources",
        type=int,
        default=120,
        help="Maximum linked resources per landing archive.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Save maximum debug artifacts: trace, events, DOM, viewports, resolve shots.",
    )
    parser.add_argument(
        "--out", default="fb_spy/results", help="Output directory root."
    )
    parser.add_argument(
        "--run-dir",
        default="",
        help="Exact output directory for this run. Overrides --out.",
    )
    parser.add_argument(
        "--octo-host",
        default="127.0.0.1",
        help="Octo Browser Local API host (default 127.0.0.1).",
    )
    parser.add_argument(
        "--octo-port",
        type=int,
        default=58888,
        help="Octo Browser Local API port (default 58888).",
    )
    parser.add_argument(
        "--octo-profile-uuid",
        default="replace-with-octo-profile-uuid",
        help="Octo Browser profile UUID to start/use.",
    )
    parser.add_argument(
        "--octo-headless",
        action="store_true",
        help="Start Octo browser profiles without a visible window.",
    )
    parser.add_argument(
        "--topic",
        default="",
        help="Optional Facebook mobile search topic to scroll instead of the home feed.",
    )
    return parser
