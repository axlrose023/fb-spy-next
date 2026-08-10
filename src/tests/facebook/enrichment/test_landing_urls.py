from __future__ import annotations

import pytest

from app.facebook.enrichment import external_landing_url, parse_landing

pytestmark = pytest.mark.unit


def test_landing_parser_separates_stable_url_tracking_and_ad_id() -> None:
    clean, tracking, ad_id = parse_landing(
        "https://offer.example/path?utm_source=facebook"
        "&utm_content=123456789012&ad_id=999999999999"
        "&fbclid=tracking&ignored=value#result"
    )

    assert clean == "https://offer.example/path"
    assert tracking == {
        "utm_source": "facebook",
        "utm_content": "123456789012",
        "fbclid": "tracking",
    }
    assert ad_id == "999999999999"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://offer.example/?sub5=111111111111", "111111111111"),
        ("https://offer.example/?utm_id=222222222222", "222222222222"),
        ("https://offer.example/?ad_id=short", None),
    ],
)
def test_landing_parser_preserves_identifier_fallback_order(
    url: str,
    expected: str | None,
) -> None:
    assert parse_landing(url)[2] == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://offer.example/path?a=1", "https://offer.example/path?a=1"),
        (
            "https://l.facebook.com/l.php?"
            "u=https%3A%2F%2Foffer.example%2Fpath%3Fa%3D1&h=tracking",
            "https://offer.example/path?a=1",
        ),
        ("https://m.facebook.com/story.php?id=1", None),
        ("mailto:test@example.com", None),
        (None, None),
    ],
)
def test_external_landing_url_unwraps_only_external_http_targets(
    url: str | None,
    expected: str | None,
) -> None:
    assert external_landing_url(url) == expected
