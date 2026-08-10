from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.facebook.calibration import (
    CalibrationDecision,
    CalibrationIntensityPolicy,
    CalibrationProcessCommandFactory,
    CalibrationProcessEnvironment,
    build_calibration_command,
    calibration_plan_from_options,
    plan_calibration_intensity,
)
from app.facebook.profiles import Profile
from app.facebook.settings import FacebookConfig

pytestmark = pytest.mark.unit


@dataclass
class OrchestratorCalibrationOptions:
    octo_host: str = ""
    octo_port: int = 0
    octo_headless: bool | None = None
    calibration_limit: int = 20
    calibration_target_goal: int = 10
    calibration_recovery_target_limit: int = 50
    calibration_recovery_target_goal: int = 40
    calibration_low_relevance_target_goal: int = 30
    calibration_funnel_target_goal: int = 3
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


@pytest.mark.parametrize(
    ("options", "expected_environment"),
    [
        (
            OrchestratorCalibrationOptions(),
            CalibrationProcessEnvironment(
                executable="configured-python",
                octo_host="configured-host",
                octo_port=58888,
                octo_headless=True,
            ),
        ),
        (
            OrchestratorCalibrationOptions(
                octo_host="cli-host",
                octo_port=59999,
                octo_headless=False,
            ),
            CalibrationProcessEnvironment(
                executable="configured-python",
                octo_host="cli-host",
                octo_port=59999,
                octo_headless=False,
            ),
        ),
    ],
)
def test_process_factory_preserves_config_fallback_and_cli_override(
    tmp_path: Path,
    options: OrchestratorCalibrationOptions,
    expected_environment: CalibrationProcessEnvironment,
) -> None:
    settings = FacebookConfig(
        runner_python="configured-python",
        octo_host="configured-host",
        octo_port=58888,
        octo_headless=True,
    )
    profile = Profile("profile", expected_country="Spain")
    ads_paths = [tmp_path / "ads.relevant.json"]
    factory = CalibrationProcessCommandFactory(settings)

    actual = factory.build(
        profile,
        options,
        tmp_path,
        ads_paths,
        "Spain",
        target_offset=7,
        target_limit=30,
        min_successful_targets=18,
        max_reactions=9,
        max_follows=3,
        max_comments=2,
        min_interactions=4,
    )
    expected = build_calibration_command(
        profile,
        options,
        tmp_path,
        ads_paths,
        "Spain",
        expected_environment,
        target_offset=7,
        target_limit=30,
        min_successful_targets=18,
        max_reactions=9,
        max_follows=3,
        max_comments=2,
        min_interactions=4,
    )

    assert actual == expected


def test_intensity_options_map_to_domain_policy() -> None:
    options = OrchestratorCalibrationOptions(calibration_offer_funnel=False)
    decision = CalibrationDecision(
        status="calibrate",
        should_calibrate=True,
        severity="high",
        reasons=["zero_relevant_ads"],
    )
    policy = CalibrationIntensityPolicy(
        standard_limit=20,
        standard_goal=10,
        recovery_limit=50,
        recovery_goal=40,
        low_relevance_goal=30,
        funnel_enabled=False,
        funnel_goal=3,
        max_reactions=6,
        max_follows=2,
        max_comments=0,
        min_interactions=1,
        comment_every=0,
    )

    assert calibration_plan_from_options(
        decision,
        options,
        available_targets=36,
    ) == plan_calibration_intensity(
        decision,
        policy,
        available_targets=36,
    )
