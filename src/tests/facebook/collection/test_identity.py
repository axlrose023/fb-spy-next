import pytest

from app.facebook.collection import (
    CollectedAd,
    creative_identity,
    is_lazy_video_image,
)

pytestmark = pytest.mark.unit


def test_creative_identity_ignores_rotating_query_parameters() -> None:
    first = CollectedAd(
        advertiser="Publisher",
        ad_type="link",
        creative_img="https://CDN.test/image.jpg?token=one",
    )
    second = CollectedAd(
        advertiser="Publisher",
        ad_type="link",
        creative_img="https://cdn.test/image.jpg?token=two",
    )

    assert creative_identity(first.creative_img) == "cdn.test/image.jpg"
    assert first.dedup_key() == second.dedup_key()


@pytest.mark.parametrize(
    ("url", "has_video", "area", "expected"),
    [
        ("https://cdn.test/profile_p135x135_token.jpg", True, 80_000, True),
        ("https://cdn.test/profile_p135x135_token.jpg", False, 80_000, False),
        ("https://cdn.test/profile_p135x135_token.jpg", True, 40_000, False),
        ("https://cdn.test/poster_p1200x628_token.jpg", True, 80_000, False),
    ],
)
def test_lazy_video_identity_requires_small_thumbnail_and_large_area(
    url: str,
    has_video: bool,
    area: int,
    expected: bool,
) -> None:
    assert (
        is_lazy_video_image(
            url,
            has_video=has_video,
            creative_area=area,
        )
        is expected
    )
