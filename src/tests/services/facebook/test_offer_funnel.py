from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from app.facebook.calibration import (
    CalibrationTarget,
    OfferFunnelPolicy,
    OfferFunnelSession,
    OfferIdentity,
    detect_success,
    domain_allowed,
    handle_offer_form,
    load_offer_identity,
    redact_error,
    redact_url,
)
from app.facebook.calibration.adapters.playwright.post_viewer import locate_saved_post

pytestmark = pytest.mark.integration


class _FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/prelander"):
            body = """
                <html><body style="height:2400px">
                  <h1>Relevant story</h1>
                  <div style="height:1800px">Long article</div>
                  <a id="offer-cta" href="/quiz">Register now</a>
                </body></html>
            """
        elif self.path.startswith("/white"):
            body = """
                <html><body>
                  <h1>Public news page</h1>
                  <p>Thank you for visiting our public page.</p>
                  <a href="/white?page=2">Pagina siguiente</a>
                </body></html>
            """
        elif self.path == "/iframe-host":
            body = '<html><body><iframe src="/iframe-form"></iframe></body></html>'
        elif self.path == "/iframe-form":
            body = """
                <html><body>
                  <form onsubmit="submitLead(event)">
                    <label>Name <input name="name" autocomplete="name"></label>
                    <label>Email <input name="email" type="email"></label>
                    <label>Phone <input name="phone" type="tel"></label>
                    <button type="submit">Register</button>
                  </form>
                  <script>
                    function submitLead(event) {
                      event.preventDefault();
                      window.location.href = '/success';
                    }
                  </script>
                </body></html>
            """
        elif self.path == "/quiz":
            body = """
                <html><body>
                  <button id="start" onclick="startQuiz()">Start</button>
                  <div id="question" style="display:none">
                    <button class="answer-btn" onclick="showForm()">Yes</button>
                    <button class="answer-btn" onclick="showForm()">No</button>
                  </div>
                  <form id="lead" style="display:none" onsubmit="submitLead(event)">
                    <label>First name <input name="first_name"></label>
                    <label>Last name <input name="last_name"></label>
                    <label>Email <input name="email" type="email"></label>
                    <div class="iti">
                      <button type="button" class="iti__selected-country">Country</button>
                      <span class="iti__country" data-country-code="ca">Canada</span>
                      <label>Phone <input name="phone" type="tel"></label>
                    </div>
                    <button type="submit">Register</button>
                  </form>
                  <script>
                    function startQuiz() {
                      document.querySelector('#start').style.display = 'none';
                      document.querySelector('#question').style.display = 'block';
                    }
                    function showForm() {
                      document.querySelector('#question').style.display = 'none';
                      document.querySelector('#lead').style.display = 'block';
                    }
                    function submitLead(event) {
                      event.preventDefault();
                      window.location.href = '/success';
                    }
                  </script>
                </body></html>
            """
        elif self.path == "/success":
            body = "<html><body><h1>Registration received</h1></body></html>"
        else:
            self.send_response(404)
            self.end_headers()
            return
        payload = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format: str, *_args) -> None:
        pass


@pytest.fixture(scope="module")
def fixture_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture(scope="module")
def chromium_browser():
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except PlaywrightError as exc:
            pytest.skip(f"Playwright Chromium is unavailable: {exc}")
        try:
            yield browser
        finally:
            browser.close()


def test_direct_offer_funnel_completes_quiz_form_and_success(
    chromium_browser,
    fixture_server,
) -> None:
    context = chromium_browser.new_context()
    session = OfferFunnelSession(
        context,
        policy=OfferFunnelPolicy(
            browse_seconds=0.2,
            max_scrolls=4,
            quiz_max_questions=3,
            submit_mode="allowlisted",
            submit_allow_domains=("127.0.0.1",),
            success_wait_seconds=3,
            navigation_timeout_ms=5_000,
        ),
        identity=OfferIdentity(
            first_name="Test",
            last_name="Lead",
            email="test.lead@example.test",
            phone="+12025550123",
            country_code="CA",
        ),
    )
    target = CalibrationTarget(
        url=f"{fixture_server}/prelander?ad_id=123",
        landing_full=f"{fixture_server}/prelander?ad_id=123&campaign_id=456",
        landing_clean=f"{fixture_server}/prelander",
        fb_ad_id="123",
    )

    try:
        result = session.run(target)

        assert result["opening"] == "direct_offer"
        assert result["status"] == "success_confirmed"
        assert result["success_confirmed"] is True
        assert set(result["fields_filled"]) == {
            "first_name",
            "last_name",
            "email",
            "phone",
        }
        assert session.summary()["submitted_targets"] == 1
        assert session.summary()["retained_tabs"] == 1

        repeated = session.run(target)
        assert repeated["form_status"] == "repeat_submit_blocked"
        assert repeated["success_confirmed"] is False
        assert session.summary()["submitted_targets"] == 1
    finally:
        session.close()
        context.close()


def test_submit_is_blocked_outside_allowlist(chromium_browser) -> None:
    context = chromium_browser.new_context()
    page = context.new_page()
    page.set_content(
        """
        <form>
          <input name="first_name">
          <input name="email" type="email">
          <input name="phone" type="tel">
          <button type="submit">Register</button>
        </form>
        """
    )
    result = handle_offer_form(
        page,
        policy=OfferFunnelPolicy(
            submit_mode="allowlisted",
            submit_allow_domains=("allowed.example",),
        ),
        identity=OfferIdentity("Test", "Lead", "test@example.test", "+12025550123"),
    )

    assert result["status"] == "submit_domain_not_allowed"
    assert result["submitted"] is False
    context.close()


def test_form_inside_iframe_can_confirm_success(
    chromium_browser,
    fixture_server,
) -> None:
    context = chromium_browser.new_context()
    session = OfferFunnelSession(
        context,
        policy=OfferFunnelPolicy(
            browse_seconds=0,
            submit_mode="allowlisted",
            submit_allow_domains=("127.0.0.1",),
            success_wait_seconds=3,
            navigation_timeout_ms=5_000,
        ),
        identity=OfferIdentity(
            first_name="QA",
            last_name="User",
            email="qa@example.test",
            phone="+12025550123",
        ),
    )
    target = CalibrationTarget(
        url=f"{fixture_server}/iframe-host",
        landing_full=f"{fixture_server}/iframe-host",
        landing_clean=f"{fixture_server}/iframe-host",
        fb_ad_id="iframe-form",
    )

    try:
        result = session.run(target)

        assert result["status"] == "success_confirmed"
        assert result["success_confirmed"] is True
        assert set(result["fields_filled"]) == {"full_name", "email", "phone"}
    finally:
        session.close()
        context.close()


def test_cross_domain_white_page_is_not_engaged(
    chromium_browser,
    fixture_server,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.facebook.calibration.funnel.adapters.playwright.landing.same_site",
        lambda _left, _right: False,
    )
    context = chromium_browser.new_context()
    session = OfferFunnelSession(
        context,
        policy=OfferFunnelPolicy(
            browse_seconds=0,
            submit_mode="disabled",
            navigation_timeout_ms=5_000,
        ),
    )
    target = CalibrationTarget(
        url=f"{fixture_server}/white",
        landing_full=f"{fixture_server}/white?ad_id=123",
        landing_clean=f"{fixture_server}/white",
        fb_ad_id="white-page",
    )

    try:
        result = session.run(target)

        assert result["status"] == "redirected_without_offer_signals"
        assert result["steps"][0]["cross_domain_redirect"] is True
        assert session.summary()["retained_tabs"] == 0
    finally:
        session.close()
        context.close()


def test_same_domain_page_without_offer_signals_is_only_viewed(
    chromium_browser,
    fixture_server,
) -> None:
    context = chromium_browser.new_context()
    session = OfferFunnelSession(
        context,
        policy=OfferFunnelPolicy(
            browse_seconds=0,
            max_scrolls=0,
            submit_mode="disabled",
            navigation_timeout_ms=5_000,
        ),
    )
    target = CalibrationTarget(
        url=f"{fixture_server}/white",
        landing_full=f"{fixture_server}/white",
        landing_clean=f"{fixture_server}/white",
    )

    try:
        result = session.run(target)

        assert result["status"] == "landing_viewed"
        assert session.summary()["retained_tabs"] == 0
    finally:
        session.close()
        context.close()


def test_saved_post_does_not_match_reused_post_with_conflicting_metadata(
    chromium_browser,
) -> None:
    context = chromium_browser.new_context()
    page = context.new_page()
    page.set_content(
        """
        <article data-store="post_id:122251694486122450">
          <a>Kyle Buchanan Sarah</a>
          <div>AMAZON.CA</div>
          <h2>{{product.name}}</h2>
          <button aria-label="Like">Like</button>
          <button aria-label="Comment">Comment</button>
          <button>Learn more</button>
        </article>
        """
    )
    target = CalibrationTarget(
        url="https://m.facebook.com/61553673501112/posts/122251694486122450",
        facebook_post_url=(
            "https://m.facebook.com/61553673501112/posts/122251694486122450"
        ),
        advertiser="Kyle Buchanan Sarah",
        displayed_domain="moderninsightreport.com",
        headline="Get Details",
    )

    try:
        result = locate_saved_post(page, target)

        assert result["status"] == "post_not_found"
        assert result["advertiser_in_page"] is True
    finally:
        context.close()


def test_mismatched_facebook_cta_uses_saved_direct_offer(
    chromium_browser,
    fixture_server,
    monkeypatch,
) -> None:
    context = chromium_browser.new_context()
    source_page = context.new_page()
    source_page.set_content("<main>Saved Facebook post</main>")
    wrong_page = context.new_page()
    wrong_page.set_content(
        """
        <main>
          <h1>Unrelated destination</h1>
          <form><input type="email"><button>Register now</button></form>
        </main>
        """
    )

    monkeypatch.setattr(
        "app.facebook.calibration.funnel.adapters.playwright.landing.open_ad_landing",
        lambda *_args, **_kwargs: (
            {
                "action": "landing_visit",
                "status": "visited",
                "landing_url": "https://wrong.example/?fbclid=secret",
                "landing_domain": "wrong.example",
                "expected_domain_match": False,
            },
            wrong_page,
            [wrong_page],
        ),
    )
    session = OfferFunnelSession(
        context,
        policy=OfferFunnelPolicy(
            browse_seconds=0,
            quiz_max_questions=2,
            submit_mode="disabled",
            navigation_timeout_ms=5_000,
        ),
    )
    target = CalibrationTarget(
        url=f"{fixture_server}/prelander",
        facebook_post_url="https://m.facebook.com/100/posts/200",
        landing_full=f"{fixture_server}/prelander?ad_id=123",
        landing_clean=f"{fixture_server}/prelander",
        fb_ad_id="mismatch-fallback",
    )

    try:
        result = session.run(target, source_page=source_page, element_id="post")

        assert result["opening"] == "direct_offer"
        assert result["status"] == "form_ready"
        opening = result["steps"][0]
        assert opening["fallback_reason"] == "cta_domain_mismatch"
        assert opening["facebook_cta_attempt"]["landing_url"] == (
            "https://wrong.example/"
        )
    finally:
        session.close()
        if not source_page.is_closed():
            source_page.close()
        context.close()


def test_url_and_success_helpers_do_not_expose_query_values() -> None:
    assert redact_url("https://offer.example/click?token=secret&ad_id=123") == (
        "https://offer.example/click"
    )
    assert domain_allowed(
        "https://sub.offer.example/path",
        ("offer.example",),
    )
    assert not domain_allowed("https://offer.example.evil/path", ("offer.example",))
    error = redact_error(
        "Page.goto failed at https://offer.example/click?access_token=secret&ad_id=1"
    )
    assert error == "Page.goto failed at https://offer.example/click"


def test_success_detector_uses_confirmation_page(chromium_browser) -> None:
    context = chromium_browser.new_context()
    page = context.new_page()
    page.set_content("<main>Registration received</main>")

    assert detect_success(page)
    context.close()


def test_dangerous_form_is_never_filled_or_submitted(chromium_browser) -> None:
    context = chromium_browser.new_context()
    page = context.new_page()
    page.set_content(
        """
        <form>
          <input name="email" type="email">
          <input name="phone" type="tel">
          <input name="card_number" aria-label="Credit card number">
          <button type="submit">Register</button>
        </form>
        """
    )
    result = handle_offer_form(
        page,
        policy=OfferFunnelPolicy(
            submit_mode="allowlisted",
            submit_allow_domains=("allowed.example",),
        ),
        identity=OfferIdentity("Test", "Lead", "test@example.test", "+12025550123"),
    )

    assert result["status"] == "blocked_dangerous_fields"
    assert result["fields_filled"] == []
    assert result["submitted"] is False
    context.close()


def test_identity_can_be_selected_per_profile_or_country(tmp_path) -> None:
    path = tmp_path / "identities.json"
    path.write_text(
        json.dumps(
            {
                "profiles": {
                    "profile-ca": {
                        "first_name": "Profile",
                        "email": "profile@example.test",
                        "phone": "+12025550123",
                        "country_code": "ca",
                    }
                },
                "countries": {
                    "Spain": {
                        "first_name": "Country",
                        "email": "country@example.test",
                        "phone": "+34910000000",
                        "country_code": "es",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    by_profile = load_offer_identity(path, profile_uuid="profile-ca", country="Canada")
    by_country = load_offer_identity(path, profile_uuid="other", country="spain")

    assert by_profile.first_name == "Profile"
    assert by_profile.country_code == "CA"
    assert by_country.first_name == "Country"
    assert by_country.country_code == "ES"
