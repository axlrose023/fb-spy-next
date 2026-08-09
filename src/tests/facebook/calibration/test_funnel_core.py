from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from playwright.sync_api import BrowserContext

from app.facebook.calibration import (
    CalibrationTarget,
    OfferFunnelPolicy,
    OfferFunnelSession,
    OfferIdentity,
    domain_allowed,
    load_offer_identity,
    offer_url,
    public_offer_target,
    redact_error,
    redact_url,
)
from app.facebook.calibration.funnel.adapters.playwright.landing import (
    open_funnel_landing,
)
from app.facebook.calibration.funnel.service import funnel_status
from app.services.facebook import offer_funnel as legacy_funnel

pytestmark = pytest.mark.unit


def test_offer_submission_is_disabled_by_default() -> None:
    policy = OfferFunnelPolicy()

    assert policy.submit_mode == "disabled"
    assert policy.submit_allow_domains == ()


def test_offer_identity_requires_name_email_and_phone() -> None:
    complete = OfferIdentity("First", "Last", "lead@example.test", "+12025550123")

    assert complete.full_name == "First Last"
    assert complete.complete is True
    assert (
        OfferIdentity(first_name="First", email="invalid", phone="123").complete
        is False
    )


def test_legacy_offer_funnel_module_is_a_public_api_facade() -> None:
    assert legacy_funnel.OfferFunnelPolicy is OfferFunnelPolicy
    assert legacy_funnel.OfferFunnelSession is OfferFunnelSession
    assert legacy_funnel.domain_allowed is domain_allowed
    assert legacy_funnel.redact_url is redact_url


def test_identity_selection_prefers_profile_then_casefolded_country(
    tmp_path: Path,
) -> None:
    path = tmp_path / "identities.json"
    path.write_text(
        json.dumps(
            {
                "profiles": {"profile-ca": {"first_name": "Profile"}},
                "countries": {"Spain": {"first_name": "Country"}},
                "default": {"first_name": "Default"},
            }
        ),
        encoding="utf-8",
    )

    assert load_offer_identity(path, profile_uuid="profile-ca").first_name == "Profile"
    assert load_offer_identity(path, country="spain").first_name == "Country"
    assert load_offer_identity(path, country="other").first_name == "Default"


def test_identity_loader_is_empty_without_path_and_rejects_non_object(
    tmp_path: Path,
) -> None:
    assert load_offer_identity(None) == OfferIdentity()
    path = tmp_path / "invalid.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="must contain an object"):
        load_offer_identity(path)


def test_redaction_and_allowlist_do_not_leak_or_accept_suffix_confusion() -> None:
    secret_url = "https://offer.example/path?token=secret&ad_id=123"

    assert redact_url(secret_url) == "https://offer.example/path"
    assert redact_error(f"failed at {secret_url}") == (
        "failed at https://offer.example/path"
    )
    assert domain_allowed("https://sub.offer.example/path", ("offer.example",))
    assert not domain_allowed("https://offer.example.evil/path", ("offer.example",))


def test_public_target_contains_only_redacted_and_domain_level_urls() -> None:
    target = CalibrationTarget(
        url="https://m.facebook.com/100/posts/200?tracking=secret",
        facebook_post_url="https://m.facebook.com/100/posts/200?tracking=secret",
        landing_full="https://offer.example/path?token=secret",
        advertiser="Example",
        country="Canada",
        fb_ad_id="123",
    )

    assert offer_url(target) == "https://offer.example/path?token=secret"
    assert public_offer_target(target) == {
        "advertiser": "Example",
        "country": "Canada",
        "fb_ad_id": "123",
        "facebook_post_url": "https://m.facebook.com/100/posts/200",
        "landing_domain": "offer.example",
    }


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"success_confirmed": True}, "success_confirmed"),
        ({"form_status": "detected"}, "form_ready"),
        ({"form_status": "submitted_unconfirmed"}, "form_submitted_unconfirmed"),
        ({"form_status": "blocked_dangerous_fields"}, "unsafe_form_blocked"),
        ({"status": "landing_viewed"}, "landing_viewed"),
    ],
)
def test_funnel_status_maps_security_and_submission_outcomes(
    result: dict[str, object],
    expected: str,
) -> None:
    assert funnel_status(result) == expected


class _NoBrowserContext:
    def new_page(self) -> None:
        raise AssertionError("fail-closed fallback must not start a browser page")


def test_direct_offer_fallback_fails_closed_without_navigation() -> None:
    context = cast(BrowserContext, _NoBrowserContext())
    target = CalibrationTarget(url="not-a-url")

    disabled = open_funnel_landing(
        context,
        OfferFunnelPolicy(direct_offer_fallback=False),
        target,
        source_page=None,
        element_id="",
    )
    missing = open_funnel_landing(
        context,
        OfferFunnelPolicy(direct_offer_fallback=True),
        target,
        source_page=None,
        element_id="",
    )

    assert disabled.result["status"] == "direct_fallback_disabled"
    assert missing.result["status"] == "missing_direct_offer_url"
