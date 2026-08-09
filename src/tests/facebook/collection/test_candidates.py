from __future__ import annotations

import pytest

from app.facebook.collection import CollectedAd, CollectionService

pytestmark = pytest.mark.unit


def detection(**overrides: object) -> dict[str, object]:
    raw: dict[str, object] = {
        "advertiser": "Publisher",
        "ad_type": "link",
        "has_video": False,
        "domain": "offer.test",
        "headline": "Breaking report",
        "ad_text": "Read this report",
        "cta": "Learn more",
        "cta_href": "https://offer.test/start",
        "creative_img": "https://cdn.test/creative.jpg?token=one",
        "creative_area": 80_000,
        "element_id": "first",
    }
    raw.update(overrides)
    return raw


def test_exact_candidate_is_deduplicated_and_refreshes_element_id() -> None:
    service = CollectionService()
    first = service.consider_detection(detection(), country="Canada")
    service.accept(first)

    duplicate = service.consider_detection(
        detection(
            creative_img="https://cdn.test/creative.jpg?token=two",
            element_id="second",
        ),
        country="Canada",
    )

    assert duplicate.accepted is False
    assert duplicate.reason == "exact_duplicate"
    assert service.registry.ads[first.key].feed_element_id == "second"


def test_lazy_video_thumbnail_is_replaced_by_loaded_creative() -> None:
    service = CollectionService()
    lazy = service.consider_detection(
        detection(
            has_video=True,
            ad_type="video",
            creative_img="https://cdn.test/profile_p135x135_token.jpg",
        ),
        country="Canada",
    )
    lazy.ad.landing_full = "https://offer.test/loaded"
    lazy.ad.video = "videos/already.mp4"
    service.accept(lazy)

    loaded = service.consider_detection(
        detection(
            has_video=True,
            ad_type="video",
            creative_img="https://cdn.test/video-poster-1200.jpg",
        ),
        country="Canada",
    )

    assert loaded.accepted is True
    assert loaded.removed_keys == (lazy.key,)
    assert loaded.ad.landing_full == "https://offer.test/loaded"
    assert loaded.ad.video == "videos/already.mp4"
    service.accept(loaded)
    assert set(service.registry.ads) == {loaded.key}


def test_lazy_candidate_does_not_replace_loaded_sibling() -> None:
    service = CollectionService()
    loaded = service.consider_detection(detection(), country=None)
    service.accept(loaded)

    lazy = service.consider_detection(
        detection(
            has_video=True,
            ad_type="video",
            creative_img="https://cdn.test/profile_p135x135_token.jpg",
        ),
        country=None,
    )

    assert lazy.accepted is False
    assert lazy.reason == "lazy_media_duplicate"
    assert lazy.related_keys == (loaded.key,)
    assert set(service.registry.ads) == {loaded.key}


def test_duplicate_resolved_ad_id_removes_candidate_and_blocks_coarse_key() -> None:
    service = CollectionService()
    first = service.consider_detection(detection(headline="One"), country=None)
    service.accept(first)
    first.ad.fb_ad_id = "123"
    assert service.register_resolved(first) is True

    second = service.consider_detection(detection(headline="Two"), country=None)
    service.accept(second)
    second.ad.fb_ad_id = "123"
    assert service.register_resolved(second) is False
    assert second.key not in service.registry.ads

    repeated = service.consider_detection(detection(headline="Two"), country=None)
    assert repeated.accepted is False
    assert repeated.reason == "confirmed_duplicate"


def test_detection_maps_persisted_contract() -> None:
    decision = CollectionService().consider_detection(
        detection(fb_ad_id="42", facebook_post_url="https://facebook.com/1/posts/2"),
        country="Canada",
    )

    assert decision.ad == CollectedAd(
        advertiser="Publisher",
        ad_type="link",
        country="Canada",
        displayed_domain="offer.test",
        headline="Breaking report",
        ad_text="Read this report",
        cta="Learn more",
        cta_href="https://offer.test/start",
        creative_img="https://cdn.test/creative.jpg?token=one",
        feed_element_id="first",
        fb_ad_id="42",
        facebook_post_url="https://facebook.com/1/posts/2",
        captured_at=decision.ad.captured_at,
    )
