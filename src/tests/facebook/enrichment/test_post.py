from __future__ import annotations

import pytest

from app.facebook.enrichment.post import matching_visible_feed_row, valid_post_url

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
