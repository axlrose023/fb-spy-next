from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.facebook.calibration import (
    CalibrationProcessEnvironment,
    build_calibration_command,
)
from app.facebook.profiles import Profile

pytestmark = pytest.mark.unit


@dataclass
class CalibrationOptions:
    calibration_limit: int = 20
    calibration_view_seconds: float = 45
    calibration_pause: float = 2
    calibration_locate_timeout: float = 12
    calibration_page_timeout: float = 45
    calibration_landing_view_seconds: float = 45
    calibration_landing_timeout: float = 20
    calibration_session_minutes: float = 15
    calibration_prelander_max_scrolls: int = 12
    calibration_quiz_max_questions: int = 10
    calibration_offer_submit_mode: str = "disabled"
    calibration_offer_success_wait_seconds: float = 20
    calibration_max_retained_offer_tabs: int = 6
    calibration_reaction_rate: float = 0.65
    calibration_follow_rate: float = 0.2
    calibration_comment_every: int = 0
    calibration_max_reactions: int = 6
    calibration_max_follows: int = 2
    calibration_max_comments: int = 0
    calibration_min_interactions: int = 1
    calibration_visit_landing: bool = True
    calibration_offer_funnel: bool = True
    calibration_direct_offer_fallback: bool = True
    calibration_repeat_targets_until_deadline: bool = True
    calibration_offer_identity_json: str = ""
    calibration_offer_submit_allow_domain: list[str] = field(default_factory=list)
    calibration_comment_template: list[str] = field(default_factory=list)


def environment(*, headless: bool = False) -> CalibrationProcessEnvironment:
    return CalibrationProcessEnvironment(
        executable="python",
        octo_host="127.0.0.1",
        octo_port=58888,
        octo_headless=headless,
    )


def option_value(command: list[str], name: str) -> str:
    return command[command.index(name) + 1]


def test_default_calibration_command_preserves_policy_defaults(tmp_path: Path) -> None:
    ads_paths = [tmp_path / "first.json", tmp_path / "second.json"]

    command = build_calibration_command(
        Profile("profile"),
        CalibrationOptions(),
        tmp_path / "calibration",
        ads_paths,
        "Spain",
        environment(),
    )

    assert command[:3] == ["python", "-m", "app.services.facebook_calibrator"]
    assert option_value(command, "--limit") == "20"
    assert option_value(command, "--target-offset") == "0"
    assert option_value(command, "--min-successful-targets") == "3"
    assert option_value(command, "--country") == "Spain"
    assert [
        command[index + 1]
        for index, value in enumerate(command)
        if value == "--ads-json"
    ] == [str(path) for path in ads_paths]
    assert "--visit-landing" in command
    assert "--offer-funnel" in command
    assert "--direct-offer-fallback" in command
    assert "--repeat-targets-until-deadline" in command
    assert "--octo-headless" not in command


def test_overrides_and_optional_values_are_forwarded_in_order(tmp_path: Path) -> None:
    options = CalibrationOptions(
        calibration_offer_identity_json="identity.json",
        calibration_offer_submit_allow_domain=["one.example", "two.example"],
        calibration_comment_template=["first", "second"],
    )

    command = build_calibration_command(
        Profile("profile", no_country_filter=True),
        options,
        tmp_path,
        [],
        "Ignored",
        environment(headless=True),
        target_offset=-5,
        target_limit=50,
        min_successful_targets=30,
        max_reactions=15,
        max_follows=7,
        max_comments=4,
        min_interactions=8,
    )

    assert option_value(command, "--target-offset") == "0"
    assert option_value(command, "--limit") == "50"
    assert option_value(command, "--min-successful-targets") == "30"
    assert option_value(command, "--max-reactions") == "15"
    assert option_value(command, "--max-follows") == "7"
    assert option_value(command, "--max-comments") == "4"
    assert option_value(command, "--min-interactions") == "8"
    assert "--no-country-filter" in command
    assert "--country" not in command
    assert command[-1] == "--octo-headless"
    assert command.count("--offer-submit-allow-domain") == 2
    assert command.count("--comment-template") == 2


def test_disabled_funnel_and_negative_timings_are_clamped(tmp_path: Path) -> None:
    options = CalibrationOptions(
        calibration_locate_timeout=-1,
        calibration_page_timeout=-1,
        calibration_landing_view_seconds=-1,
        calibration_landing_timeout=-1,
        calibration_session_minutes=-1,
        calibration_prelander_max_scrolls=-1,
        calibration_quiz_max_questions=-1,
        calibration_offer_success_wait_seconds=-1,
        calibration_max_retained_offer_tabs=0,
        calibration_visit_landing=False,
        calibration_offer_funnel=False,
        calibration_direct_offer_fallback=False,
        calibration_repeat_targets_until_deadline=False,
    )

    command = build_calibration_command(
        Profile("profile"), options, tmp_path, [], None, environment()
    )

    for name in (
        "--locate-timeout-ms",
        "--timeout-ms",
        "--landing-view-seconds",
        "--landing-timeout-ms",
        "--session-minutes",
        "--prelander-max-scrolls",
        "--quiz-max-questions",
        "--offer-success-wait-seconds",
    ):
        assert option_value(command, name) in {"0", "0.0"}
    assert option_value(command, "--max-retained-offer-tabs") == "1"
    assert "--no-visit-landing" in command
    assert "--no-offer-funnel" in command
    assert "--no-direct-offer-fallback" in command
    assert "--no-repeat-targets-until-deadline" in command
    assert "--country" not in command
