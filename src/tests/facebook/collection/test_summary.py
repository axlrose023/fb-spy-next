import json
from pathlib import Path

import pytest

from app.facebook.collection import CollectedAd, ad_summary
from app.facebook.collection.artifacts import write_json_atomic

pytestmark = pytest.mark.unit


def test_summary_preserves_collector_metric_shape() -> None:
    ads = {
        "one": CollectedAd(
            advertiser="Publisher",
            ad_type="link",
            country="Canada",
            displayed_domain="offer.test",
            landing_clean="https://offer.test/path",
            fb_ad_id="1",
            screenshot="screens/one.png",
            screenshot_ok=True,
        ),
        "two": CollectedAd(
            advertiser="Publisher",
            ad_type="video",
            has_video=True,
            country="Canada",
            displayed_domain="video.test",
            screenshot="screens/two.png",
            screenshot_ok=False,
        ),
    }

    assert ad_summary(ads) == {
        "unique_ads": 2,
        "by_type": {"link": 1, "video": 1},
        "countries": {"Canada": 2},
        "resolved_landings": 1,
        "unique_landing_clean": 1,
        "unique_fb_ad_ids": 1,
        "unique_advertisers": 1,
        "unique_domains": 2,
        "screenshot_attempted": 2,
        "screenshot_ok": 1,
        "video_ads": 1,
    }


def test_collector_json_artifacts_are_private(tmp_path: Path) -> None:
    path = tmp_path / "ads.json"

    write_json_atomic(path, [{"landing_full": "https://offer.example/?token=x"}])

    assert json.loads(path.read_text(encoding="utf-8"))[0]["landing_full"]
    assert path.stat().st_mode & 0o777 == 0o600
