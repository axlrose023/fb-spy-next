from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.facebook.profiles import Profile

from ..models import CalibrationPolicy


@dataclass(frozen=True, slots=True)
class CalibrationProcessEnvironment:
    executable: str
    octo_host: str
    octo_port: int
    octo_headless: bool


class CalibrationCommandOptions(Protocol):
    calibration_limit: int
    calibration_view_seconds: float
    calibration_pause: float
    calibration_locate_timeout: float
    calibration_page_timeout: float
    calibration_landing_view_seconds: float
    calibration_landing_timeout: float
    calibration_session_minutes: float
    calibration_prelander_max_scrolls: int
    calibration_quiz_max_questions: int
    calibration_offer_submit_mode: str
    calibration_offer_success_wait_seconds: float
    calibration_max_retained_offer_tabs: int
    calibration_reaction_rate: float
    calibration_follow_rate: float
    calibration_comment_every: int
    calibration_max_reactions: int
    calibration_max_follows: int
    calibration_max_comments: int
    calibration_min_interactions: int
    calibration_visit_landing: bool
    calibration_offer_funnel: bool
    calibration_direct_offer_fallback: bool
    calibration_repeat_targets_until_deadline: bool
    calibration_offer_identity_json: str
    calibration_offer_submit_allow_domain: list[str]
    calibration_comment_template: list[str]


def build_calibration_command(
    profile: Profile,
    options: CalibrationCommandOptions,
    run_dir: Path,
    ads_paths: list[Path],
    country: str | None,
    environment: CalibrationProcessEnvironment,
    *,
    target_offset: int = 0,
    target_limit: int | None = None,
    min_successful_targets: int | None = None,
    max_reactions: int | None = None,
    max_follows: int | None = None,
    max_comments: int | None = None,
    min_interactions: int | None = None,
) -> list[str]:
    command = [
        environment.executable,
        "-m",
        "app.facebook.calibration.commands",
        "--octo-host",
        environment.octo_host,
        "--octo-port",
        str(environment.octo_port),
        "--octo-profile-uuid",
        profile.octo_profile_uuid,
        "--limit",
        str(target_limit if target_limit is not None else options.calibration_limit),
        "--target-offset",
        str(max(0, target_offset)),
        "--view-seconds",
        str(options.calibration_view_seconds),
        "--pause-between-targets",
        str(options.calibration_pause),
        "--locate-timeout-ms",
        str(round(max(0.0, options.calibration_locate_timeout) * 1000)),
        "--timeout-ms",
        str(round(max(0.0, options.calibration_page_timeout) * 1000)),
        "--landing-view-seconds",
        str(max(0.0, options.calibration_landing_view_seconds)),
        "--landing-timeout-ms",
        str(round(max(0.0, options.calibration_landing_timeout) * 1000)),
        "--session-minutes",
        str(max(0.0, options.calibration_session_minutes)),
        "--prelander-max-scrolls",
        str(max(0, options.calibration_prelander_max_scrolls)),
        "--quiz-max-questions",
        str(max(0, options.calibration_quiz_max_questions)),
        "--offer-submit-mode",
        str(options.calibration_offer_submit_mode),
        "--offer-success-wait-seconds",
        str(max(0.0, options.calibration_offer_success_wait_seconds)),
        "--max-retained-offer-tabs",
        str(max(1, options.calibration_max_retained_offer_tabs)),
        "--reaction-rate",
        str(options.calibration_reaction_rate),
        "--follow-rate",
        str(options.calibration_follow_rate),
        "--comment-every",
        str(options.calibration_comment_every),
        "--max-reactions",
        str(
            max_reactions
            if max_reactions is not None
            else options.calibration_max_reactions
        ),
        "--max-follows",
        str(
            max_follows if max_follows is not None else options.calibration_max_follows
        ),
        "--max-comments",
        str(
            max_comments
            if max_comments is not None
            else options.calibration_max_comments
        ),
        "--min-interactions",
        str(
            min_interactions
            if min_interactions is not None
            else options.calibration_min_interactions
        ),
        "--min-successful-targets",
        str(
            min_successful_targets
            if min_successful_targets is not None
            else CalibrationPolicy().min_successful_calibration_targets
        ),
        "--run-dir",
        str(run_dir),
        "--target-health-json",
        str(run_dir.parent / "calibration_target_health.json"),
    ]
    command.append(
        "--visit-landing" if options.calibration_visit_landing else "--no-visit-landing"
    )
    command.append(
        "--offer-funnel" if options.calibration_offer_funnel else "--no-offer-funnel"
    )
    command.append(
        "--direct-offer-fallback"
        if options.calibration_direct_offer_fallback
        else "--no-direct-offer-fallback"
    )
    command.append(
        "--repeat-targets-until-deadline"
        if options.calibration_repeat_targets_until_deadline
        else "--no-repeat-targets-until-deadline"
    )
    if options.calibration_offer_identity_json:
        command.extend(
            ["--offer-identity-json", options.calibration_offer_identity_json]
        )
    for domain in options.calibration_offer_submit_allow_domain:
        command.extend(["--offer-submit-allow-domain", domain])
    for template in options.calibration_comment_template:
        command.extend(["--comment-template", template])
    if profile.no_country_filter:
        command.append("--no-country-filter")
    elif country:
        command.extend(["--country", country])
    for ads_path in ads_paths:
        command.extend(["--ads-json", str(ads_path)])
    if environment.octo_headless:
        command.append("--octo-headless")
    return command
