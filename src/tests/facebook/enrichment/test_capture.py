from __future__ import annotations

from pathlib import Path

import pytest

from app.facebook.enrichment import EnrichmentOptions, RelevantAd
from app.facebook.enrichment.adapters.playwright import capture
from app.services import facebook_runner

pytestmark = pytest.mark.unit


class FakePage:
    def __init__(self) -> None:
        self.closed = False

    def wait_for_timeout(self, _milliseconds: int) -> None:
        pass

    def close(self, *, run_before_unload: bool) -> None:
        self.closed = True


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self.page = page

    def new_page(self) -> FakePage:
        return self.page


def test_failed_post_match_closes_page_and_preserves_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    page = FakePage()
    monkeypatch.setattr(capture, "goto_with_retry", lambda *_a, **_k: None)
    monkeypatch.setattr(
        capture,
        "wait_for_saved_post",
        lambda *_a, **_k: {"status": "post_not_found"},
    )
    monkeypatch.setattr(facebook_runner, "_pause_ad_video", lambda *_a: None)
    candidate = RelevantAd.from_raw(
        {
            "relevance_gate": "allow",
            "advertiser": "Kept",
            "facebook_post_url": "https://m.facebook.com/1/posts/2",
        }
    )

    result = capture.enrich_allowed_ad(
        FakeContext(page),
        candidate,
        sequence=1,
        run_dir=tmp_path,
        options=EnrichmentOptions(wait_after_load=0),
    )

    assert result.details["status"] == "failed"
    assert result.ad["advertiser"] == "Kept"
    assert page.closed is True
