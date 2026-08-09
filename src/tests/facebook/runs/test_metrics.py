from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.facebook.runs.metrics import collect_run_metrics
from app.facebook.runs.metrics.evidence import (
    clean_landing_key,
    domain_key,
    has_relevance,
    is_relevant,
)
from app.facebook.runs.metrics.loading import (
    elapsed_from_timestamps,
    load_ads,
    load_json,
)
from app.facebook.runs.metrics.normalization import (
    bool_or_none,
    float_or_none,
    geo_matches,
    hourly_rate,
    int_or_none,
    parse_datetime,
    per_100,
    safe_div,
)

pytestmark = pytest.mark.unit


def test_collect_metrics_uses_classified_ads_and_fallback_timestamps(
    tmp_path: Path,
) -> None:
    ads = [
        {
            "ad_type": "link" if index < 8 else "video",
            "fb_ad_id": str(index),
            "advertiser": f"Brand {index % 2}",
            "country": "Canada" if index < 8 else "Spain",
            "landing_full": f"https://www.example.com/offer/{index}?utm=x",
            "screenshot": f"screens/{index}.png",
            "screenshot_ok": index != 9,
            "captured_at": f"2026-08-01T10:{index:02d}:00Z",
            "relevance": {"result": "relevant" if index < 3 else "not_relevant"},
        }
        for index in range(9)
    ]
    ads.append(
        {
            "ad_type": "in_facebook",
            "country": "Canada",
            "captured_at": "2026-08-01T10:10:00Z",
        }
    )
    (tmp_path / "ads.classified.json").write_text(
        json.dumps(ads),
        encoding="utf-8",
    )
    (tmp_path / "run_meta.json").write_text(
        json.dumps(
            {
                "started_at": "2026-08-01T10:00:00Z",
                "profile_country": "Canada",
                "expected_country": "Canada",
                "connection_data": {"ip": "203.0.113.2"},
                "octo_headless": "yes",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "summary.json").write_text(
        json.dumps({"scrolls": 100, "duplicate_fb_ad_ids": "2"}),
        encoding="utf-8",
    )

    metrics = collect_run_metrics(tmp_path, calibration_targets_available=7)

    assert metrics.elapsed_seconds == 600
    assert metrics.ads_total == 10
    assert metrics.link_ads == 8
    assert metrics.video_ads == 1
    assert metrics.in_facebook_ads == 1
    assert metrics.relevance_known is True
    assert metrics.relevant_ads == 3
    assert metrics.relevant_rate == pytest.approx(1 / 3)
    assert metrics.target_source == "relevance"
    assert metrics.country_match_rate == pytest.approx(0.9)
    assert metrics.geo_match is True
    assert metrics.octo_ip == "203.0.113.2"
    assert metrics.octo_headless is True
    assert metrics.duplicate_fb_ad_ids == 2
    assert metrics.target_per_100_scrolls == 3
    assert metrics.calibration_targets_available == 7


def test_loading_and_url_normalization_tolerate_corrupt_evidence(
    tmp_path: Path,
) -> None:
    (tmp_path / "ads.classified.json").write_text("{}", encoding="utf-8")
    (tmp_path / "ads.json").write_text("not-json", encoding="utf-8")
    (tmp_path / "ads.partial.json").write_text(
        json.dumps([{"fb_ad_id": "1"}, "ignored"]),
        encoding="utf-8",
    )

    assert load_ads(tmp_path) == []
    (tmp_path / "ads.json").unlink()
    assert load_ads(tmp_path) == [{"fb_ad_id": "1"}]
    assert load_json(tmp_path / "missing.json", default={"ok": False}) == {"ok": False}
    assert domain_key("") == ""
    assert domain_key("www.Example.com/path") == "example.com"
    assert domain_key("http://[") == "http://["
    assert clean_landing_key(None) == ""
    assert clean_landing_key("http://[") == "http://["


@pytest.mark.parametrize(
    ("payload", "known", "relevant"),
    [
        ({"relevant": True}, True, True),
        ({"relevant": False}, True, False),
        ({"relevance": "relevant"}, True, True),
        ({"relevance": "not_relevant"}, True, False),
        ({"relevance": {"result": "relevant"}}, True, True),
        ({"relevance": {"result": "unknown"}}, False, False),
        ({}, False, False),
    ],
)
def test_relevance_evidence_shapes(
    payload: dict[str, object],
    known: bool,
    relevant: bool,
) -> None:
    assert has_relevance(payload) is known
    assert is_relevant(payload) is relevant


def test_numeric_boolean_and_time_normalization_edges() -> None:
    naive = datetime(2026, 8, 1, 10)

    assert parse_datetime(naive) == naive.replace(tzinfo=UTC)
    assert parse_datetime("bad") is None
    assert float_or_none("") is None
    assert float_or_none("bad") is None
    assert int_or_none(None) is None
    assert int_or_none("bad") is None
    assert bool_or_none(None) is None
    assert bool_or_none(False) is False
    assert bool_or_none("off") is False
    assert bool_or_none("maybe") is None
    assert geo_matches(None, "Spain") is True
    assert geo_matches("Spain", "spain") is True
    assert safe_div(1, 0) is None
    assert hourly_rate(None, 1) is None
    assert hourly_rate(1, 0) is None
    assert per_100(1, None) is None
    assert elapsed_from_timestamps("bad", "2026-08-01T10:00:00Z") is None
    assert (
        elapsed_from_timestamps(
            "2026-08-01T11:00:00Z",
            "2026-08-01T10:00:00Z",
        )
        == 0
    )
