from __future__ import annotations

import pytest

from app.facebook.collection import ArtifactPolicy

pytestmark = pytest.mark.unit


def test_interest_safe_policy_disables_every_active_artifact() -> None:
    policy = ArtifactPolicy.from_options(
        screenshots=True,
        landing_resolution=True,
        video_recording=True,
        permalink_resolution=True,
        interest_safe=True,
    )

    assert policy.screenshots is True
    assert policy.landing_resolution is False
    assert policy.video_recording is False
    assert policy.permalink_resolution is False
    assert policy.overrides == (
        "landing_resolution",
        "video_recording",
        "permalink_resolution",
    )


def test_active_policy_preserves_requested_actions() -> None:
    policy = ArtifactPolicy.from_options(
        screenshots=False,
        landing_resolution=True,
        video_recording=False,
        permalink_resolution=True,
        interest_safe=False,
    )

    assert policy.landing_resolution is True
    assert policy.video_recording is False
    assert policy.permalink_resolution is True
    assert policy.overrides == ()
