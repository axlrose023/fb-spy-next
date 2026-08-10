import pytest

from app.ad_library.ads.ingestion.language import (
    language_from_raw_ad,
    normalize_ad_language,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("English", "en"),
        ("en", "en"),
        ("EN-US", "en"),
        ("Turkish", "tr"),
        ("türkçe", "tr"),
        ("Spanish", "es"),
        ("es", "es"),
        ("Filipino", "fil"),
        ("Tagalog/English", "fil"),
        ("Turkish, Russian", "tr"),
        ("Arabic", "ar"),
        ("Czech", "cs"),
        ("Portuguese (Brazil)", "pt"),
        ("", None),
        ("not-a-language", None),
    ],
)
def test_normalize_ad_language(value, expected) -> None:
    assert normalize_ad_language(value) == expected


def test_language_from_raw_ad_prefers_direct_value() -> None:
    assert (
        language_from_raw_ad(
            {
                "language": "Spanish",
                "relevance": {"language": "English"},
            }
        )
        == "es"
    )


def test_language_from_raw_ad_reads_relevance() -> None:
    assert language_from_raw_ad({"relevance": {"language": "Turkish"}}) == "tr"
