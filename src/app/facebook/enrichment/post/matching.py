from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


def matching_visible_feed_row(
    rows: Any,
    expected: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(rows, list):
        return None
    candidates = [
        (feed_row_match_score(row, expected), row)
        for row in rows
        if isinstance(row, dict)
    ]
    candidates = [
        (score, row)
        for score, row in candidates
        if score >= 7 and row.get("element_id")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        return None
    return candidates[0][1]


def feed_row_match_score(
    observed: dict[str, Any],
    expected: dict[str, Any],
) -> int:
    expected_domain = normalized_text(expected.get("displayed_domain"))
    observed_domain = normalized_text(
        observed.get("domain") or observed.get("displayed_domain")
    )
    if expected_domain and observed_domain != expected_domain:
        return -1
    score = 4 if expected_domain else 0
    if _same_text(observed, expected, "advertiser"):
        score += 4
    if _text_prefix_match(observed, expected, "headline"):
        score += 3
    expected_creative = url_path(expected.get("creative_img"))
    observed_creative = url_path(observed.get("creative_img"))
    if expected_creative and expected_creative == observed_creative:
        score += 4
    if _text_prefix_match(observed, expected, "ad_text"):
        score += 2
    return score


def merge_passive_identity(
    raw: dict[str, Any],
    observed: dict[str, Any],
) -> None:
    mapping = {
        "feed_element_id": "element_id",
        "displayed_domain": "domain",
        "facebook_post_url": "facebook_post_url",
        "facebook_page_url": "facebook_page_url",
        "fb_ad_id": "fb_ad_id",
        "cta_href": "cta_href",
    }
    for target, source in mapping.items():
        if not raw.get(target) and observed.get(source):
            raw[target] = observed[source]


def normalized_text(value: Any) -> str:
    return " ".join(re.findall(r"\w+", str(value or "").casefold()))


def url_path(value: Any) -> str:
    try:
        return urlparse(str(value or "")).path.casefold()
    except ValueError:
        return ""


def _same_text(
    observed: dict[str, Any],
    expected: dict[str, Any],
    key: str,
) -> bool:
    expected_value = normalized_text(expected.get(key))
    return bool(expected_value and expected_value == normalized_text(observed.get(key)))


def _text_prefix_match(
    observed: dict[str, Any],
    expected: dict[str, Any],
    key: str,
) -> bool:
    expected_value = normalized_text(expected.get(key))
    observed_value = normalized_text(observed.get(key))
    return bool(
        expected_value
        and observed_value
        and (
            expected_value.startswith(observed_value)
            or observed_value.startswith(expected_value)
        )
    )
