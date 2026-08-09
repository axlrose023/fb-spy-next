from __future__ import annotations

import pytest

from app.facebook.calibration import (
    calibration_pool_name,
    is_direct_calibration_target,
    is_relevant_ad,
    merge_calibration_ads,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"relevant": True}, True),
        ({"relevance": {"result": "relevant"}}, True),
        ({"relevance": "ReLeVaNt"}, True),
        ({"relevant": False, "relevance": {"result": "irrelevant"}}, False),
    ],
)
def test_relevant_ad_compatibility_forms(
    payload: dict[str, object], expected: bool
) -> None:
    assert is_relevant_ad(payload) is expected


@pytest.mark.parametrize(
    "target",
    [
        {"facebook_post_url": "https://m.facebook.com/100/posts/200"},
        {"facebook_post_url": ("https://facebook.com/story.php?story_fbid=200&id=100")},
        {"landing_full": "https://offer.example/path"},
    ],
)
def test_direct_target_accepts_saved_post_or_offer(target: dict[str, object]) -> None:
    assert is_direct_calibration_target({**target, "relevance": {"result": "relevant"}})


def test_direct_target_rejects_irrelevant_or_unusable_urls() -> None:
    assert not is_direct_calibration_target(
        {
            "facebook_post_url": "https://example.com/100/posts/200",
            "relevance": {"result": "relevant"},
        }
    )
    assert not is_direct_calibration_target(
        {
            "landing_full": "javascript:alert(1)",
            "relevance": {"result": "relevant"},
        }
    )
    assert not is_direct_calibration_target(
        {"landing_full": "https://offer.example", "relevant": False}
    )
    assert not is_direct_calibration_target(
        {
            "facebook_post_url": "https://[invalid",
            "landing_full": "https://otherwise-valid.example",
            "relevant": True,
        }
    )
    assert not is_direct_calibration_target(
        {"landing_full": "https://[invalid", "relevant": True}
    )


def test_pool_merge_prefers_fresh_and_deduplicates_identity() -> None:
    fresh = [
        {
            "fb_ad_id": "same",
            "landing_full": "https://fresh.example",
            "relevant": True,
        }
    ]
    previous = [
        {
            "fb_ad_id": "same",
            "landing_full": "https://old.example",
            "relevant": True,
        },
        {
            "landing_full": "https://second.example",
            "relevant": True,
        },
        {"landing_full": "https://irrelevant.example"},
    ]

    assert merge_calibration_ads(fresh, previous) == [fresh[0], previous[1]]


def test_pool_merge_honors_zero_limit_and_country_name_is_stable() -> None:
    ad = {"landing_full": "https://offer.example", "relevant": True}
    another = {"landing_full": "https://second.example", "relevant": True}

    assert merge_calibration_ads([ad], [], limit=0) == []
    assert merge_calibration_ads([ad, another], [], limit=1) == [ad]
    assert calibration_pool_name("Saudi Arabia / Тест") == "saudi_arabia"
    assert calibration_pool_name("Тест") == "unknown"
