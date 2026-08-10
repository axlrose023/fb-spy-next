from __future__ import annotations

import pytest

from app.facebook.collection import CollectedAd
from app.facebook.enrichment.post import (
    OPEN_COMMENTS_FOR_PERMALINK_JS,
    facebook_post_identity_from_url,
    matching_visible_feed_row,
    normalized_facebook_post_url,
    resolve_facebook_post_url,
    valid_post_url,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://m.facebook.com/1/posts/2", True),
        ("https://www.facebook.com/story.php?id=1&story_fbid=2", True),
        ("https://facebook.com/", False),
        ("https://example.test/1/posts/2", False),
    ],
)
def test_only_direct_facebook_post_urls_are_accepted(
    value: str, expected: bool
) -> None:
    assert bool(valid_post_url(value)) is expected


def test_ambiguous_feed_match_fails_closed() -> None:
    expected = {"displayed_domain": "offer.test", "advertiser": "Publisher"}
    rows = [
        {"domain": "offer.test", "advertiser": "Publisher", "element_id": "a"},
        {"domain": "offer.test", "advertiser": "Publisher", "element_id": "b"},
    ]

    assert matching_visible_feed_row(rows, expected) is None


def test_strongest_unique_feed_match_is_selected() -> None:
    expected = {
        "displayed_domain": "offer.test",
        "advertiser": "Publisher",
        "headline": "Breaking report",
    }
    rows = [
        {"domain": "offer.test", "advertiser": "Publisher", "element_id": "weak"},
        {
            "domain": "offer.test",
            "advertiser": "Publisher",
            "headline": "Breaking report...",
            "element_id": "strong",
        },
    ]

    match = matching_visible_feed_row(rows, expected)

    assert match is not None
    assert match["element_id"] == "strong"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://m.facebook.com/story.php?story_fbid=200&id=100&refid=52",
            ("100", "200"),
        ),
        ("https://www.facebook.com/100/posts/200?mibextid=abc", ("100", "200")),
        ("https://example.com/100/posts/200", None),
    ],
)
def test_facebook_post_identity_is_host_bound(
    url: str,
    expected: tuple[str, str] | None,
) -> None:
    assert facebook_post_identity_from_url(url) == expected


def test_post_url_normalization_discards_tracking_state() -> None:
    assert (
        normalized_facebook_post_url(
            "https://m.facebook.com/story.php?id=100&story_fbid=200&refid=52"
        )
        == "https://m.facebook.com/story.php?story_fbid=200&id=100"
    )
    assert (
        normalized_facebook_post_url(
            "https://www.facebook.com/100/posts/200?mibextid=abc"
        )
        == "https://m.facebook.com/100/posts/200"
    )


class StaticAdPage:
    def __init__(self) -> None:
        self.url = "https://m.facebook.com/"
        self.keyboard = self

    def evaluate(self, script: str, payload: dict[str, str]) -> dict[str, str]:
        assert script == OPEN_COMMENTS_FOR_PERMALINK_JS
        assert payload == {"elementId": "feed-element"}
        self.url = "https://m.facebook.com/story.php?story_fbid=200&id=100"
        return {"status": "clicked", "label": "comment"}

    def wait_for_timeout(self, _timeout: int) -> None:
        pass

    def go_back(self, **_kwargs: object) -> None:
        self.url = "https://m.facebook.com/"

    def press(self, _key: str) -> None:
        pass


def test_permalink_recovery_updates_ad_and_restores_feed() -> None:
    page = StaticAdPage()
    ad = CollectedAd(advertiser="Saved advertiser", ad_type="link")

    resolved = resolve_facebook_post_url(page, ad, "feed-element")

    assert resolved is True
    assert ad.facebook_page_url == "https://m.facebook.com/100"
    assert ad.facebook_post_url == (
        "https://m.facebook.com/story.php?story_fbid=200&id=100"
    )
    assert page.url == "https://m.facebook.com/"
