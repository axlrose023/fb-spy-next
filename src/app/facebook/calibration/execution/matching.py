from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from ..planning.target_pool import CalibrationTarget


def find_matching_target(
    row: dict[str, Any],
    targets: list[CalibrationTarget],
) -> tuple[CalibrationTarget | None, int]:
    best_target = None
    best_score = 0
    for target in targets:
        score = target_match_score(row, target)
        if score > best_score:
            best_target = target
            best_score = score
    return (best_target, best_score) if best_score >= 12 else (None, best_score)


def target_match_score(row: dict[str, Any], target: CalibrationTarget) -> int:
    element_id = str(row.get("element_id") or "")
    if target.feed_element_id and element_id == target.feed_element_id:
        return 100

    row_domain = normalized_domain(row.get("domain"))
    target_domain = normalized_domain(
        target.displayed_domain or target.landing_clean or target.url
    )
    domain_match = bool(row_domain and target_domain and row_domain == target_domain)
    row_advertiser = normalized_text(row.get("advertiser"))
    target_advertiser = normalized_text(target.advertiser)
    advertiser_match = bool(
        row_advertiser and target_advertiser and row_advertiser == target_advertiser
    )
    headline_similarity = similarity(row.get("headline"), target.headline)
    body_similarity = similarity(row.get("ad_text"), target.ad_text)

    score = 12 if domain_match else 0
    score += 7 if advertiser_match else 0
    score += 6 if headline_similarity >= 0.80 else 0
    score += 4 if body_similarity >= 0.75 else 0
    return score


def live_ad_key(row: dict[str, Any]) -> str:
    values = (
        row.get("advertiser"),
        row.get("domain"),
        row.get("headline"),
        row.get("ad_text"),
        row.get("creative_img"),
    )
    return "\x1f".join(normalized_text(value) for value in values)


def normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def normalized_domain(value: Any) -> str:
    cleaned = normalized_text(value)
    cleaned = re.sub(r"^https?://", "", cleaned).split("/", 1)[0]
    return cleaned.removeprefix("www.")


def similarity(left: Any, right: Any) -> float:
    first = normalized_text(left)
    second = normalized_text(right)
    if not first or not second:
        return 0.0
    if first == second:
        return 1.0
    return SequenceMatcher(None, first, second).ratio()
