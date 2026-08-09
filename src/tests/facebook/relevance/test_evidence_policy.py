import pytest

from app.facebook.relevance.evidence import (
    isolated_external_url,
    resolution_candidate,
    summarize_isolated_resolutions,
)

pytestmark = pytest.mark.unit


def test_isolated_url_decodes_redirect_and_strips_profile_state() -> None:
    target, issue = isolated_external_url(
        "https://l.facebook.com/l.php?"
        "u=https%3A%2F%2Foffer.example%2Fstart%3F"
        "campaign_id%3D123%26fbclid%3Dprofile-token",
        host_is_public=lambda host: host == "offer.example",
    )

    assert issue == ""
    assert target == "https://offer.example/start?campaign_id=123"


def test_resolution_prefers_passive_cta_then_anonymous_post() -> None:
    direct = resolution_candidate(
        {
            "cta_href": "https://offer.example/start",
            "facebook_post_url": "https://m.facebook.com/1/posts/2",
        },
        host_is_public=lambda host: host == "offer.example",
    )
    fallback = resolution_candidate(
        {"facebook_post_url": "https://m.facebook.com/1/posts/2"},
        host_is_public=lambda _host: False,
    )

    assert direct.source == "passive_cta_href"
    assert fallback.source == "anonymous_facebook_post"


def test_isolation_summary_fails_closed_on_profile_cookie() -> None:
    summary = summarize_isolated_resolutions(
        [
            {
                "relevance_gate": "hold",
                "isolated_resolution": {
                    "status": "completed",
                    "landing_resolved": True,
                    "landing_screenshot_saved": True,
                    "cookie_isolated": True,
                    "separate_browser_context": True,
                    "facebook_cookie_count_before": 1,
                    "authenticated_profile_context": False,
                    "active_profile_actions_started": False,
                    "isolated_navigation_started": True,
                },
            }
        ],
        status="completed",
        finished_at="2026-08-09T00:00:00Z",
    )

    assert summary["resolved"] == 1
    assert summary["isolation_violations"] == 1
