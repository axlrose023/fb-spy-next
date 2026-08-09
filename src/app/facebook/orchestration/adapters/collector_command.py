from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.facebook.profiles import Profile

from .command_environment import OctoProcessEnvironment


class CollectorCommandOptions(Protocol):
    collect_minutes: float
    collect_scrolls: int
    resolve_max: int
    scroll_px: int
    max_ads_per_view: int
    landing_archive_timeout: float
    landing_archive_max_resources: int
    video_max_seconds: float
    debug: bool
    interest_safe_collection: bool
    no_video_recording: bool
    no_landing_archives: bool


def build_collector_command(
    profile: Profile,
    options: CollectorCommandOptions,
    run_dir: Path,
    environment: OctoProcessEnvironment,
) -> list[str]:
    command = [
        environment.executable,
        "-m",
        environment.collector_module,
        "--minutes",
        str(options.collect_minutes),
        "--collect-scrolls",
        str(options.collect_scrolls),
        "--resolve-max",
        str(options.resolve_max),
        "--scroll-px",
        str(options.scroll_px),
        "--max-ads-per-view",
        str(options.max_ads_per_view),
        "--landing-archive-timeout",
        str(options.landing_archive_timeout),
        "--landing-archive-max-resources",
        str(options.landing_archive_max_resources),
        "--video-max-seconds",
        str(options.video_max_seconds),
        "--octo-host",
        environment.host,
        "--octo-port",
        str(environment.port),
        "--octo-profile-uuid",
        profile.octo_profile_uuid,
        "--run-dir",
        str(run_dir),
    ]
    if options.debug:
        command.append("--debug")
    if options.interest_safe_collection:
        command.append("--passive-collect")
    if options.no_video_recording:
        command.append("--no-video-recording")
    if options.no_landing_archives:
        command.append("--no-landing-archives")
    if environment.headless:
        command.append("--octo-headless")
    return command
