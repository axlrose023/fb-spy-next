from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.facebook.enrichment.adapters.playwright import post as enrichment_post
from app.facebook.relevance import (
    RelevanceResult,
    apply_prefilter_uncertainty_guard,
    parse_model_json,
)
from app.services import (
    facebook_isolated_landing_resolver as isolated_resolver,
)
from app.services import facebook_orchestrator, facebook_runner
from app.services import facebook_relevance_classifier as classifier
from app.services.facebook_ad_enricher import (
    _candidate_indexes,
    _enrich_one,
    _matching_visible_feed_row,
    _recover_allowed_post_url,
    _summary,
    _valid_post_url,
)
from app.services.facebook_orchestrator import ProfileConfig


def test_model_json_accepts_uncertain_only_for_explicit_prefilter() -> None:
    response = '{"result":"uncertain","reason":"Landing evidence is required."}'

    assert parse_model_json(response)["result"] == "not_relevant"
    assert (
        parse_model_json(
            response,
            allowed_results={"relevant", "not_relevant", "uncertain"},
        )["result"]
        == "uncertain"
    )


def test_sparse_link_card_is_held_instead_of_definitively_denied() -> None:
    raw = {
        "advertiser": "Mary Z King",
        "ad_type": "link",
        "displayed_domain": "newscoolstop.digital",
        "headline": "newscoolstop.digital",
        "ad_text": "",
        "cta": "",
        "creative_img": ("https://scontent.example/v/t39.30808-1/profile_p135x135.jpg"),
        "facebook_post_url": "https://m.facebook.com/1/posts/2",
    }

    result = apply_prefilter_uncertainty_guard(
        raw,
        {
            "result": "not_relevant",
            "reason": "No visible finance evidence.",
        },
    )

    assert result["result"] == "uncertain"
    assert result["prefilter_original_result"] == "not_relevant"


def test_complete_out_of_scope_link_card_remains_denied() -> None:
    raw = {
        "ad_type": "link",
        "displayed_domain": "shop.example",
        "headline": "Summer shoes",
        "ad_text": "Buy branded running shoes.",
        "cta": "Shop now",
        "creative_img": "https://cdn.example/creative-1200x628.jpg",
        "facebook_post_url": "https://m.facebook.com/1/posts/2",
    }
    denied = {"result": "not_relevant", "reason": "Ordinary retail ad."}

    assert apply_prefilter_uncertainty_guard(raw, denied) == denied


def test_feed_only_analysis_removes_every_active_enrichment_artifact() -> None:
    raw = {
        "advertiser": "News",
        "screenshot": "screens/ad.png",
        "video": "videos/ad.mp4",
        "landing_full": "https://example.test/?fbclid=secret",
        "landing_clean": "https://example.test/",
        "landing_screenshot": "landing_screens/page.png",
        "landing_archive": "landing_archives/page.zip",
        "utm": {"fbclid": "secret"},
    }

    result = classifier._analysis_input(
        raw,
        include_video=False,
        feed_only=True,
    )

    assert result == {
        "advertiser": "News",
        "screenshot": "screens/ad.png",
    }


def test_only_allowed_rows_can_enter_active_enrichment() -> None:
    rows = [
        {"relevance_gate": "deny"},
        {"relevance_gate": "allow"},
        {"relevance_gate": "hold"},
        {"relevance_gate": "allow"},
    ]

    assert _candidate_indexes(rows) == [1, 3]


def test_enrichment_summary_detects_any_action_on_blocked_row() -> None:
    rows = [
        {
            "relevance_gate": "deny",
            "enrichment": {"active_actions_started": True},
        },
        {
            "relevance_gate": "allow",
            "enrichment": {
                "active_actions_started": True,
                "cta_click_attempted": True,
                "landing_resolved": True,
            },
        },
    ]

    result = _summary(rows, status="completed")

    assert result["active_actions_on_blocked_ads"] == 1
    assert result["active_candidates"] == 2
    assert result["landing_click_attempts"] == 1


def test_enrich_one_refuses_blocked_row_before_browser_access(tmp_path: Path) -> None:
    enriched, result = _enrich_one(
        None,
        {
            "advertiser": "Blocked",
            "relevance_gate": "deny",
            "facebook_post_url": "https://m.facebook.com/123/posts/456",
        },
        sequence=1,
        run_dir=tmp_path,
        args=SimpleNamespace(),
    )

    assert result["status"] == "blocked_by_relevance_gate"
    assert result["active_actions_started"] is False
    assert enriched["enrichment"] == result


def test_post_url_recovery_refuses_blocked_row_before_browser_access() -> None:
    post_url, result = _recover_allowed_post_url(
        None,
        {"relevance_gate": "deny"},
        args=SimpleNamespace(),
    )

    assert post_url == ""
    assert result["status"] == "blocked_by_relevance_gate"
    assert result["profile_navigation_started"] is False


class _NeutralizedFeedPage:
    def __init__(self) -> None:
        self.url = "about:blank"
        self.went_back = False

    def go_back(self, **_kwargs):
        self.went_back = True
        self.url = "https://m.facebook.com/"

    def evaluate(self, _script, _payload=None):
        return True

    def wait_for_timeout(self, _milliseconds: int) -> None:
        pass


def test_allowed_post_url_is_recovered_from_neutralized_feed_history(
    monkeypatch,
) -> None:
    page = _NeutralizedFeedPage()
    context = SimpleNamespace(pages=[page])
    neutralized = []
    monkeypatch.setattr(
        facebook_runner,
        "prepare_passive_media_guard",
        lambda _page: {"init_script_installed": True},
    )
    monkeypatch.setattr(
        facebook_runner,
        "install_passive_media_guard",
        lambda _page: True,
    )

    def resolve(_page, ad, element_id, **_kwargs):
        assert element_id == "fbspy_saved"
        ad.facebook_post_url = "https://m.facebook.com/123/posts/456"
        ad.facebook_page_url = "https://m.facebook.com/123"
        return True

    monkeypatch.setattr(enrichment_post, "resolve_facebook_post_url", resolve)
    monkeypatch.setattr(
        enrichment_post,
        "neutralize_profile_pages",
        lambda *_args: neutralized.append(True),
    )
    raw = {
        "relevance_gate": "allow",
        "feed_element_id": "fbspy_saved",
        "advertiser": "Relevant ad",
    }

    post_url, result = _recover_allowed_post_url(
        context,
        raw,
        args=SimpleNamespace(timeout_ms=1000, wait_after_load=0),
    )

    assert page.went_back is True
    assert post_url == "https://m.facebook.com/123/posts/456"
    assert result["status"] == "recovered"
    assert result["matched_by"] == "preserved_feed_element_id"
    assert result["profile_navigation_started"] is True
    assert neutralized == [True]


def test_feed_recovery_requires_strict_metadata_match() -> None:
    expected = {
        "advertiser": "The Balance Guru",
        "displayed_domain": "offer.example",
        "headline": "Breaking report from Canada",
    }
    rows = [
        {
            "advertiser": "Different advertiser",
            "domain": "offer.example",
            "headline": "Ordinary promotion",
            "element_id": "wrong",
        },
        {
            "advertiser": "The Balance Guru",
            "domain": "offer.example",
            "headline": "Breaking report from Canada...",
            "element_id": "right",
        },
    ]

    result = _matching_visible_feed_row(rows, expected)

    assert result is not None
    assert result["element_id"] == "right"


@pytest.mark.parametrize(
    ("url", "valid"),
    [
        ("https://m.facebook.com/123/posts/456", True),
        ("https://www.facebook.com/story.php?id=123&story_fbid=456", True),
        ("https://example.com/123/posts/456", False),
        ("https://m.facebook.com/", False),
        ("", False),
    ],
)
def test_enricher_accepts_only_direct_facebook_post_urls(url, valid) -> None:
    assert bool(_valid_post_url(url)) is valid


class _RecordingFilter:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def analyze_raw_ad(self, raw, _run_dir, **_kwargs):
        self.calls.append(raw)
        return RelevanceResult(
            True,
            {"result": "relevant", "reason": "confirmed"},
            source="combined_screenshots",
        )


@pytest.mark.asyncio
async def test_finalize_never_reclassifies_or_acts_on_denied_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        classifier,
        "get_config",
        lambda: SimpleNamespace(
            facebook=SimpleNamespace(relevance_filter_concurrency=3)
        ),
    )
    relevance_filter = _RecordingFilter()
    rows = [
        {
            "advertiser": "Shop",
            "relevance_gate": "deny",
            "prefilter_relevance": {
                "result": "not_relevant",
                "reason": "ordinary shop",
            },
            "enrichment": {
                "status": "blocked_by_relevance_gate",
                "active_actions_started": False,
            },
        },
        {
            "advertiser": "Candidate",
            "relevance_gate": "allow",
            "prefilter_relevance": {
                "result": "relevant",
                "reason": "fake-news finance funnel",
            },
            "landing_screenshot": "landing.png",
            "enrichment": {
                "status": "completed",
                "active_actions_started": True,
            },
        },
    ]

    result = await classifier._finalize_ads(
        rows,
        tmp_path,
        relevance_filter,
        include_video=False,
    )

    assert len(relevance_filter.calls) == 1
    assert relevance_filter.calls[0]["advertiser"] == "Candidate"
    assert result[0]["relevance"]["result"] == "not_relevant"
    assert result[0]["relevance_source"] == "feed_prefilter"


@pytest.mark.asyncio
async def test_isolated_landing_can_promote_hold_before_profile_enrichment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        classifier,
        "get_config",
        lambda: SimpleNamespace(
            facebook=SimpleNamespace(relevance_filter_concurrency=3)
        ),
    )
    relevance_filter = _RecordingFilter()
    rows = [
        {
            "advertiser": "Sparse candidate",
            "relevance_gate": "hold",
            "prefilter_relevance": {
                "result": "uncertain",
                "reason": "Landing required.",
            },
            "landing_full": "https://example.test/offer",
            "landing_screenshot": "landing_screens/offer.png",
            "isolated_resolution": {
                "status": "completed",
                "landing_resolved": True,
                "cookie_isolated": True,
                "authenticated_profile_context": False,
                "active_profile_actions_started": False,
            },
        }
    ]

    result = await classifier._resolve_held_ads(
        rows,
        tmp_path,
        relevance_filter,
    )

    assert len(relevance_filter.calls) == 1
    assert result[0]["relevance_gate"] == "allow"
    assert result[0]["relevance_gate_source"] == "isolated_landing"
    assert result[0]["isolated_relevance"]["result"] == "relevant"


@pytest.mark.asyncio
async def test_unresolved_hold_never_enters_authenticated_profile(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        classifier,
        "get_config",
        lambda: SimpleNamespace(
            facebook=SimpleNamespace(relevance_filter_concurrency=3)
        ),
    )
    relevance_filter = _RecordingFilter()
    rows = [
        {
            "relevance_gate": "hold",
            "isolated_resolution": {
                "status": "missing_or_internal_passive_cta",
                "cookie_isolated": True,
                "authenticated_profile_context": False,
                "active_profile_actions_started": False,
            },
        }
    ]

    gated = await classifier._resolve_held_ads(
        rows,
        tmp_path,
        relevance_filter,
    )

    assert relevance_filter.calls == []
    assert gated[0]["relevance_gate"] == "hold"
    assert _candidate_indexes(gated) == []


def test_isolated_url_decodes_fb_redirect_and_removes_profile_tracking(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        isolated_resolver,
        "_host_is_public",
        lambda host: host == "offer.example",
    )
    value = (
        "https://l.facebook.com/l.php?"
        "u=https%3A%2F%2Foffer.example%2Fstart%3F"
        "campaign_id%3D123%26fbclid%3Dprofile-token"
        "&h=redirect-token"
    )

    target, issue = isolated_resolver.isolated_external_url(value)

    assert issue == ""
    assert target == "https://offer.example/start?campaign_id=123"
    assert "facebook.com" not in target
    assert "fbclid" not in target


def test_isolated_candidate_falls_back_to_anonymous_saved_post() -> None:
    source, target, issue = isolated_resolver._resolution_candidate(
        {
            "cta_href": "",
            "facebook_post_url": "https://m.facebook.com/123/posts/456",
        }
    )

    assert source == "anonymous_facebook_post"
    assert target == "https://m.facebook.com/123/posts/456"
    assert issue == ""


class _AnonymousLocatorPage:
    def __init__(self) -> None:
        self.calls = []
        self.waits = []

    def evaluate(self, _script, payload):
        self.calls.append(payload)
        if len(self.calls) == 1:
            return {"status": "post_not_found"}
        return {
            "status": "located",
            "element_id": payload["elementId"],
            "strategy": "anonymous_metadata_cta",
        }

    def wait_for_timeout(self, milliseconds: int) -> None:
        self.waits.append(milliseconds)


def test_anonymous_post_locator_requires_metadata_cta_match() -> None:
    page = _AnonymousLocatorPage()
    target = isolated_resolver.CalibrationTarget(
        url="https://m.facebook.com/123/posts/456",
        advertiser="Example News",
        displayed_domain="offer.example",
        headline="Breaking report",
        ad_text="",
        cta="Learn more",
    )

    result = isolated_resolver._wait_for_anonymous_post_cta(
        page,
        target,
        element_id="isolated-1",
        timeout_ms=1_000,
    )

    assert result["status"] == "located"
    assert result["strategy"] == "anonymous_metadata_cta"
    assert result["attempts"] == 2
    assert page.calls[0] == {
        "advertiser": "Example News",
        "displayedDomain": "offer.example",
        "headline": "Breaking report",
        "cta": "Learn more",
        "elementId": "isolated-1",
    }
    assert page.waits == [500]


@pytest.mark.parametrize(
    "value",
    [
        "https://m.facebook.com/1/posts/2",
        "http://127.0.0.1/admin",
        "http://localhost/admin",
        "http://169.254.169.254/latest/meta-data/",
    ],
)
def test_isolated_url_rejects_meta_and_private_destinations(
    value,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        isolated_resolver,
        "_host_is_public",
        lambda host: host == "public.example",
    )

    target, issue = isolated_resolver.isolated_external_url(value)

    assert target == ""
    assert issue


def test_isolated_summary_fails_closed_without_cookie_audit() -> None:
    result = isolated_resolver._summary(
        [
            {
                "relevance_gate": "hold",
                "isolated_resolution": {
                    "status": "completed",
                    "landing_resolved": True,
                    "cookie_isolated": True,
                    "separate_browser_context": True,
                    "facebook_cookie_count_before": 1,
                    "authenticated_profile_context": False,
                    "active_profile_actions_started": False,
                    "isolated_navigation_started": True,
                    "external_navigation_started": True,
                },
            }
        ],
        status="completed",
    )

    assert result["isolation_violations"] == 1


def test_orchestrator_enables_passive_collection_by_default(tmp_path: Path) -> None:
    args = facebook_orchestrator._build_parser().parse_args(["run"])
    profile = ProfileConfig(octo_profile_uuid="profile")

    command = facebook_orchestrator._collector_command(profile, args, tmp_path)

    assert "--passive-collect" in command
    assert args.interest_safe_collection is True
    assert args.relevant_enrichment is True
    assert args.isolated_hold_resolution is True


def test_orchestrator_passes_gated_source_to_active_enricher(
    tmp_path: Path,
) -> None:
    args = facebook_orchestrator._build_parser().parse_args(["run"])
    profile = ProfileConfig(octo_profile_uuid="profile")
    source = tmp_path / "ads.gated.json"

    command = facebook_orchestrator._relevant_enricher_command(
        profile,
        args,
        tmp_path,
        source=source,
    )

    assert command[command.index("--source") + 1] == str(source)


def test_orchestrator_validates_passive_collection_artifacts(tmp_path: Path) -> None:
    (tmp_path / "summary.json").write_text(
        json.dumps(
            {
                "interest_safe_mode": True,
                "resolve_enabled": False,
                "active_actions": {
                    "cta_click_attempts": 0,
                    "video_play_attempts": 0,
                    "comment_open_attempts": 0,
                },
                "passive_media_guard": {
                    "installed": True,
                    "init_script_installed": True,
                    "media_route_installed": True,
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "ads.json").write_text(
        json.dumps([{"facebook_post_url": "https://m.facebook.com/1/posts/2"}]),
        encoding="utf-8",
    )

    assert facebook_orchestrator._interest_safe_collection_violations(tmp_path) == []


def test_orchestrator_rejects_active_artifact_in_passive_collection(
    tmp_path: Path,
) -> None:
    (tmp_path / "summary.json").write_text(
        json.dumps(
            {
                "interest_safe_mode": True,
                "resolve_enabled": False,
                "active_actions": {
                    "cta_click_attempts": 1,
                    "video_play_attempts": 0,
                    "comment_open_attempts": 0,
                },
                "passive_media_guard": {
                    "installed": True,
                    "init_script_installed": True,
                    "media_route_installed": True,
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "ads.json").write_text(
        json.dumps([{"landing_full": "https://example.test"}]),
        encoding="utf-8",
    )

    violations = facebook_orchestrator._interest_safe_collection_violations(tmp_path)

    assert "nonzero_cta_click_attempts" in violations
    assert "passive_ad_contains_landing_full" in violations


def test_passive_ad_model_keeps_cta_href_without_using_it_as_an_action() -> None:
    ad = facebook_runner.Ad(
        advertiser="Advertiser",
        ad_type="link",
        cta_href="https://l.facebook.com/l.php?u=https%3A%2F%2Fexample.test",
    )

    assert ad.cta_href.startswith("https://l.facebook.com/")
