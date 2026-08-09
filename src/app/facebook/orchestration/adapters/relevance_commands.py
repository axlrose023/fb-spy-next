from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.facebook.profiles import Profile

from .command_environment import OctoProcessEnvironment, PythonProcessEnvironment


class EnrichmentCommandOptions(Protocol):
    calibration_page_timeout: float
    calibration_locate_timeout: float
    video_max_seconds: float
    landing_archive_timeout: float
    landing_archive_max_resources: int
    no_video_recording: bool
    no_landing_archives: bool


class IsolatedResolutionCommandOptions(Protocol):
    calibration_landing_timeout: float
    landing_archive_timeout: float
    landing_archive_max_resources: int


def build_relevance_classifier_command(
    run_dir: Path,
    environment: PythonProcessEnvironment,
    *,
    stage: str = "standard",
    source: Path | None = None,
    include_video: bool = False,
) -> list[str]:
    command = [
        environment.executable,
        "-m",
        "app.services.facebook_relevance_classifier",
        "--run-dir",
        str(run_dir),
    ]
    if stage != "standard":
        command.extend(["--stage", stage])
    if source is not None:
        command.extend(["--source", str(source)])
    if include_video:
        command.append("--include-video")
    return command


def build_relevant_enricher_command(
    profile: Profile,
    options: EnrichmentCommandOptions,
    run_dir: Path,
    environment: OctoProcessEnvironment,
    *,
    source: Path | None = None,
) -> list[str]:
    command = [
        environment.executable,
        "-m",
        "app.services.facebook_ad_enricher",
        "--run-dir",
        str(run_dir),
        "--octo-host",
        environment.host,
        "--octo-port",
        str(environment.port),
        "--octo-profile-uuid",
        profile.octo_profile_uuid,
        "--timeout-ms",
        str(max(1, round(options.calibration_page_timeout * 1000))),
        "--locate-timeout-ms",
        str(max(0, round(options.calibration_locate_timeout * 1000))),
        "--video-max-seconds",
        str(options.video_max_seconds),
        "--landing-archive-timeout",
        str(options.landing_archive_timeout),
        "--landing-archive-max-resources",
        str(options.landing_archive_max_resources),
    ]
    if source is not None:
        command.extend(["--source", str(source)])
    if options.no_video_recording:
        command.append("--no-record-videos")
    if options.no_landing_archives:
        command.append("--no-resolve-landings")
    if environment.headless:
        command.append("--octo-headless")
    return command


def build_isolated_landing_resolver_command(
    profile: Profile,
    options: IsolatedResolutionCommandOptions,
    run_dir: Path,
    environment: OctoProcessEnvironment,
) -> list[str]:
    command = [
        environment.executable,
        "-m",
        "app.services.facebook_isolated_landing_resolver",
        "--run-dir",
        str(run_dir),
        "--octo-host",
        environment.host,
        "--octo-port",
        str(environment.port),
        "--octo-profile-uuid",
        profile.octo_profile_uuid,
        "--timeout-ms",
        str(max(1, round(options.calibration_landing_timeout * 1000))),
        "--landing-ready-seconds",
        str(options.landing_archive_timeout),
        "--landing-archive-max-resources",
        str(options.landing_archive_max_resources),
    ]
    if environment.headless:
        command.append("--octo-headless")
    return command
