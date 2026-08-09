from types import SimpleNamespace

from app.facebook.calibration import CalibrationTarget
from app.facebook.calibration.adapters.playwright import target_engagement
from app.services import facebook_calibrator
from app.services.facebook.engagement import (
    EngagementPolicy,
    click_like,
    find_matching_target,
    follow_advertiser,
    live_ad_key,
    post_comment,
    target_match_score,
    visit_ad_landing,
    wait_for_saved_post,
)


class StubPage:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = iter(responses)
        self.url = "https://m.facebook.com/"

    def evaluate(self, _script, _args):
        return next(self.responses)

    def locator(self, _selector: str):
        return StubLocator()

    def wait_for_timeout(self, _timeout: int) -> None:
        pass

    def wait_for_load_state(self, _state: str, *, timeout: int) -> None:
        self.url = "https://m.facebook.com/profile.php?id=123"

    def title(self) -> str:
        return "Example Advertiser"

    def go_back(self, *, wait_until: str, timeout: int) -> None:
        self.url = "https://m.facebook.com/"


class StubLocator:
    def evaluate(self, _script: str, *, timeout: int) -> bool:
        return True


class LandingPage:
    def __init__(self) -> None:
        self.url = "https://offer.example/path?campaign=1"
        self.closed = False
        self.waited = 0

    def wait_for_load_state(self, _state: str, *, timeout: int) -> None:
        assert timeout > 0

    def wait_for_timeout(self, timeout: int) -> None:
        self.waited += timeout

    def title(self) -> str:
        return "Offer"

    def close(self, **_kwargs) -> None:
        self.closed = True


class LandingClickLocator:
    def __init__(self, source) -> None:
        self.source = source

    def evaluate(self, _script: str, *, timeout: int) -> bool:
        assert timeout > 0
        self.source.context.pages.append(self.source.landing)
        return True


class LandingSourcePage:
    def __init__(self) -> None:
        self.url = "https://m.facebook.com/100/posts/200"
        self.landing = LandingPage()
        self.unrelated = LandingPage()
        self.unrelated.url = "https://unrelated.example/old-tab"
        self.context = SimpleNamespace(pages=[self, self.unrelated])

    def evaluate(self, _script, _args):
        return {
            "status": "located",
            "action": "landing_visit",
            "label": "learn more",
        }

    def locator(self, _selector: str):
        return LandingClickLocator(self)

    def wait_for_timeout(self, _timeout: int) -> None:
        pass


class DirectPostPage:
    def __init__(self) -> None:
        self.url = "about:blank"
        self.requested_urls: list[str] = []
        self.responses = iter(
            [
                {"status": "located", "element_id": "saved-post", "post_id": "200"},
                {"status": "viewing", "has_video": False},
            ]
        )

    def goto(self, url: str, **_kwargs):
        self.requested_urls.append(url)
        self.url = "https://m.facebook.com/"
        return SimpleNamespace(status=200)

    def wait_for_timeout(self, _timeout: int) -> None:
        pass

    def evaluate(self, _script, _args):
        return next(self.responses)

    def close(self, **_kwargs) -> None:
        pass


class DirectPostContext:
    def __init__(self) -> None:
        self.page = DirectPostPage()

    def new_page(self) -> DirectPostPage:
        return self.page


class ClosedDirectPostContext(DirectPostContext):
    def new_page(self) -> DirectPostPage:
        raise facebook_calibrator.PlaywrightError(
            "BrowserContext.new_page: Target page, context or browser has been closed",
        )


class TransientDirectPostPage(DirectPostPage):
    def __init__(self) -> None:
        super().__init__()
        self.failures_left = 2
        self.waits: list[int] = []

    def goto(self, url: str, **_kwargs):
        self.requested_urls.append(url)
        if self.failures_left:
            self.failures_left -= 1
            raise facebook_calibrator.PlaywrightError(
                "Page.goto: net::ERR_SOCKS_CONNECTION_FAILED",
            )
        self.url = "https://m.facebook.com/"
        return SimpleNamespace(status=200)

    def wait_for_timeout(self, timeout: int) -> None:
        self.waits.append(timeout)


class FailedTransientDirectPostPage(TransientDirectPostPage):
    def __init__(self) -> None:
        super().__init__()
        self.failures_left = 3
        self.close_calls = 0

    def close(self, **_kwargs) -> None:
        self.close_calls += 1


class AccessBlockedDirectPostPage(DirectPostPage):
    def __init__(self) -> None:
        super().__init__()
        self.close_calls = 0

    def goto(self, url: str, **_kwargs):
        self.requested_urls.append(url)
        self.url = url
        return SimpleNamespace(status=403)

    def title(self) -> str:
        return "Fortinet Secure DNS Service Portal"

    def close(self, **_kwargs) -> None:
        self.close_calls += 1


class CommentComposer:
    def __init__(self) -> None:
        self.text = ""
        self.keys: list[str] = []

    def is_visible(self) -> bool:
        return True

    def fill(self, text: str) -> None:
        self.text = text

    def press(self, key: str) -> None:
        self.keys.append(key)

    def evaluate(self, _script: str, payload=None):
        if payload is not None:
            return {
                "status": "located",
                "action": "comment_submit",
                "label": "post comment",
            }
        return "TEXTAREA"

    def input_value(self) -> str:
        return ""


class CommentLocatorList:
    def __init__(self, composer: CommentComposer) -> None:
        self.composer = composer

    def all(self) -> list[CommentComposer]:
        return [self.composer]


class CommentRoot:
    def __init__(self, composer: CommentComposer) -> None:
        self.composer = composer

    @property
    def first(self):
        return self

    def locator(self, _selector: str) -> CommentLocatorList:
        return CommentLocatorList(self.composer)


class CommentPage:
    def __init__(self) -> None:
        self.composer = CommentComposer()
        self.responses = iter(
            [
                {"status": "located", "action": "comment", "label": "comment"},
                0,
                {"count": 1, "pending": False},
            ]
        )

    def evaluate(self, _script, _args):
        return next(self.responses)

    def locator(self, selector: str):
        if selector.startswith("[data-fbspy-id="):
            return CommentRoot(self.composer)
        return StubLocator()

    def wait_for_timeout(self, _timeout: int) -> None:
        pass


class KeyboardSubmitCommentPage(CommentPage):
    def __init__(self) -> None:
        super().__init__()
        self.responses = iter(
            [
                {"status": "located", "action": "comment", "label": "comment"},
                0,
                {"count": 1, "pending": False},
            ]
        )
        self.composer.evaluate = lambda _script, payload=None: (
            {"status": "submit_control_not_found", "action": "comment_submit"}
            if payload is not None
            else "TEXTAREA"
        )


class EmptyLocatorList:
    def all(self) -> list:
        return []


class MissingCommentRoot:
    @property
    def first(self):
        return self

    def locator(self, _selector: str) -> EmptyLocatorList:
        return EmptyLocatorList()


class GlobalCommentPage(CommentPage):
    def locator(self, selector: str):
        if selector.startswith("[data-fbspy-id="):
            return MissingCommentRoot()
        if selector.startswith("textarea"):
            return CommentLocatorList(self.composer)
        return StubLocator()


def test_feed_element_id_is_authoritative_match() -> None:
    target = CalibrationTarget(
        url="https://landing.example",
        feed_element_id="fbspy-42",
    )
    row = {"element_id": "fbspy-42", "domain": "different.example"}

    assert target_match_score(row, target) == 100
    assert find_matching_target(row, [target]) == (target, 100)


def test_domain_match_is_strong_enough_for_repeated_campaign() -> None:
    target = CalibrationTarget(
        url="https://scam.example/path",
        displayed_domain="www.scam.example",
        headline="Saved headline",
    )
    row = {
        "element_id": "new-element",
        "domain": "scam.example",
        "headline": "Different creative",
    }

    assert find_matching_target(row, [target]) == (target, 12)


def test_advertiser_alone_does_not_match() -> None:
    target = CalibrationTarget(
        url="https://landing.example",
        advertiser="Generic advertiser",
    )
    row = {
        "advertiser": "Generic advertiser",
        "domain": "unrelated.example",
    }

    assert find_matching_target(row, [target])[0] is None


def test_live_ad_key_normalizes_whitespace_and_case() -> None:
    first = live_ad_key(
        {
            "advertiser": " Example  Brand ",
            "domain": "EXAMPLE.COM",
            "headline": "Headline",
        }
    )
    second = live_ad_key(
        {
            "advertiser": "example brand",
            "domain": "example.com",
            "headline": "headline",
        }
    )

    assert first == second


def test_like_requires_active_state_after_click() -> None:
    page = StubPage(
        [
            {"status": "located", "action": "reaction"},
            {"status": "active", "pressed": True},
        ]
    )

    result = click_like(page, "ad-1")

    assert result["status"] == "clicked"
    assert result["confirmed"] is True


def test_like_does_not_report_unconfirmed_click_as_success(monkeypatch) -> None:
    monotonic_values = iter([0.0, 9.0])
    monkeypatch.setattr(
        "app.facebook.calibration.adapters.playwright.reaction.time.monotonic",
        lambda: next(monotonic_values),
    )
    page = StubPage(
        [
            {"status": "located", "action": "reaction"},
            {"status": "inactive"},
        ]
    )

    result = click_like(page, "ad-1")

    assert result["status"] == "click_unconfirmed"


def test_follow_requires_active_state_after_click() -> None:
    page = StubPage(
        [
            {"status": "located", "action": "advertiser"},
            {
                "status": "located",
                "action": "follow",
                "label": "seguir a example advertiser",
            },
            {"status": "active", "label": "siguiendo"},
        ]
    )

    result = follow_advertiser(page, "ad-1", "Example Advertiser")

    assert result["status"] == "clicked"
    assert result["confirmed"] is True


def test_comment_is_submitted_and_confirmed_inside_saved_post() -> None:
    page = CommentPage()

    result = post_comment(page, "saved-post", "👍")

    assert result["status"] == "posted"
    assert result["text"] == "👍"
    assert page.composer.text == "👍"
    assert page.composer.keys == []
    assert result["submit"]["status"] == "located"


def test_comment_waits_for_slow_pending_submission_to_finish() -> None:
    page = CommentPage()
    page.responses = iter(
        [
            {"status": "located", "action": "comment", "label": "comment"},
            0,
            *({"count": 1, "pending": True} for _ in range(20)),
            {"count": 1, "pending": False},
        ]
    )

    result = post_comment(page, "saved-post", "👍")

    assert result["status"] == "posted"


def test_comment_uses_enter_when_submit_button_has_no_accessible_label() -> None:
    page = KeyboardSubmitCommentPage()

    result = post_comment(page, "saved-post", "👍")

    assert result["status"] == "posted"
    assert result["submit"]["status"] == "keyboard_submitted"
    assert page.composer.keys == ["Enter"]


def test_comment_uses_global_composer_after_comments_screen_navigation() -> None:
    page = GlobalCommentPage()

    result = post_comment(page, "saved-post", "👍")

    assert result["status"] == "posted"
    assert result["composer_scope"] == "comments_screen"
    assert page.composer.keys == []


def test_wait_for_saved_post_retries_mobile_shell_render() -> None:
    page = StubPage(
        [
            {"status": "post_not_found", "post_id": "200"},
            {"status": "located", "element_id": "saved-post", "post_id": "200"},
        ]
    )
    target = CalibrationTarget(
        url="https://m.facebook.com/100/posts/200",
        advertiser="Example",
        facebook_post_url="https://m.facebook.com/100/posts/200",
    )

    result = wait_for_saved_post(page, target, timeout_ms=100)

    assert result["status"] == "located"
    assert result["attempts"] == 2


def test_reaction_is_confirmed_after_facebook_replaces_card(monkeypatch) -> None:
    results = iter(
        [
            {"status": "click_unconfirmed", "action": "reaction"},
            {"status": "already_active", "action": "reaction"},
        ]
    )
    monkeypatch.setattr(
        target_engagement,
        "click_like",
        lambda _page, _element_id: next(results),
    )
    target = CalibrationTarget(
        url="https://m.facebook.com/100/posts/200",
        facebook_post_url="https://m.facebook.com/100/posts/200",
        advertiser="Relevant advertiser",
    )
    monkeypatch.setattr(
        target_engagement,
        "locate_saved_post",
        lambda _page, _target: {"status": "located", "element_id": "replacement-post"},
    )

    result = facebook_calibrator._engage_reaction(
        object(),
        {"advertiser": "Relevant advertiser"},
        "original-post",
        target,
    )

    assert result["status"] == "clicked"
    assert result["confirmed"] is True
    assert result["confirmation"]["status"] == "already_active"


def test_interaction_counts_distinguish_existing_and_new_actions() -> None:
    counts = facebook_calibrator._interaction_counts(
        [
            {
                "ok": True,
                "actions": [
                    {"action": "reaction", "status": "already_active"},
                    {"action": "follow", "status": "clicked"},
                    {"action": "landing_visit", "status": "visited"},
                ],
            }
        ]
    )

    assert counts["successful"] == 2
    assert counts["already_active"] == 1
    assert counts["satisfied"] == 3
    assert counts["landing_visit"] == 1
    assert counts["targets_attempted"] == 1
    assert counts["posts_opened"] == 1


def test_interaction_counts_report_funnel_quality_outcomes() -> None:
    counts = facebook_calibrator._interaction_counts(
        [
            {
                "ok": True,
                "actions": [
                    {
                        "action": "offer_funnel",
                        "status": "success_confirmed",
                        "opening": "direct_offer",
                        "form_detected": True,
                        "form_submitted": True,
                        "form_status": "success_confirmed",
                    }
                ],
            },
            {
                "ok": False,
                "actions": [
                    {
                        "action": "offer_funnel",
                        "status": "redirected_without_offer_signals",
                    }
                ],
            },
            {
                "ok": True,
                "actions": [
                    {
                        "action": "offer_funnel",
                        "status": "offer_engaged",
                        "form_detected": True,
                        "form_status": "repeat_submit_blocked",
                    }
                ],
            },
            {
                "ok": False,
                "actions": [
                    {
                        "action": "offer_funnel",
                        "status": "landing_viewed",
                    }
                ],
            },
        ]
    )

    assert counts["funnel_success_confirmed"] == 1
    assert counts["funnel_forms_detected"] == 2
    assert counts["funnel_submit_attempted"] == 1
    assert counts["funnel_submit_blocked"] == 1
    assert counts["funnel_stale_redirects"] == 1
    assert counts["funnel_landing_only"] == 1
    assert counts["funnel_unusable_offers"] == 1
    assert counts["direct_offer_fallback"] == 1
    assert counts["direct_offer_fallback_attempts"] == 1
    assert counts["failed"] == 2


def test_offer_funnel_is_required_when_enabled_for_saved_post() -> None:
    assert not facebook_calibrator._calibration_target_ok(
        post_viewed=True,
        funnel_ok=False,
        funnel_required=True,
        post_required=True,
    )
    assert facebook_calibrator._calibration_target_ok(
        post_viewed=True,
        funnel_ok=True,
        funnel_required=True,
        post_required=True,
    )
    assert facebook_calibrator._calibration_target_ok(
        post_viewed=False,
        funnel_ok=True,
        funnel_required=True,
        post_required=False,
    )
    assert facebook_calibrator._calibration_target_ok(
        post_viewed=True,
        funnel_ok=False,
        funnel_required=False,
        post_required=True,
    )


def test_already_active_interaction_does_not_finish_calibration() -> None:
    args = SimpleNamespace(
        min_successful_targets=1,
        min_interactions=1,
        comment_every=0,
        max_comments=0,
    )
    results = [
        {
            "ok": True,
            "actions": [{"action": "reaction", "status": "already_active"}],
        }
    ]

    assert facebook_calibrator._calibration_goals_met(results, args) is False


def test_calibration_goals_stop_after_eight_opened_posts() -> None:
    args = SimpleNamespace(min_successful_targets=8, min_interactions=1)
    results = [{"ok": True, "actions": []} for _ in range(8)]
    results[0]["actions"] = [{"action": "reaction", "status": "clicked"}]

    assert facebook_calibrator._calibration_goals_met(results[:7], args) is False
    assert facebook_calibrator._calibration_goals_met(results, args) is True


def test_calibration_with_three_target_goal_still_reaches_fifth_comment() -> None:
    args = SimpleNamespace(
        min_successful_targets=3,
        min_interactions=1,
        comment_every=5,
        max_comments=1,
    )
    results = [{"ok": True, "actions": []} for _ in range(5)]
    results[0]["actions"] = [{"action": "reaction", "status": "clicked"}]

    assert (
        facebook_calibrator._calibration_goals_met(
            results[:3], args, targets_available=5
        )
        is False
    )
    assert (
        facebook_calibrator._calibration_goals_met(results, args, targets_available=5)
        is True
    )
    assert (
        facebook_calibrator._calibration_goals_met(
            results[:3], args, targets_available=4
        )
        is True
    )


def test_comment_is_posted_on_configured_relevant_ad_interval(monkeypatch) -> None:
    posted: list[tuple[str, str]] = []
    monkeypatch.setattr(
        target_engagement,
        "view_feed_ad",
        lambda *_args: {"status": "viewed"},
    )
    monkeypatch.setattr(
        target_engagement,
        "post_comment",
        lambda _page, element_id, text: (
            posted.append((element_id, text)) or {"status": "posted"}
        ),
    )
    policy = EngagementPolicy(
        reaction_rate=0.0,
        follow_rate=0.0,
        comment_every=2,
        max_reactions=0,
        max_follows=0,
        max_comments=4,
        min_interactions=0,
    )
    args = SimpleNamespace(
        view_seconds=0.0,
        comment_template=["👍"],
        interaction_dry_run=False,
        timeout_ms=1_000,
    )
    budget = {"reaction": 0, "follow": 0, "comment": 0, "successful": 0}

    first = facebook_calibrator._engage_row(
        object(),
        {"element_id": "ad-1"},
        CalibrationTarget(
            url="https://m.facebook.com/100/posts/201",
            facebook_post_url="https://m.facebook.com/100/posts/201",
        ),
        policy,
        budget,
        args,
        relevant_ad_number=1,
    )
    second = facebook_calibrator._engage_row(
        object(),
        {"element_id": "ad-2"},
        CalibrationTarget(
            url="https://m.facebook.com/100/posts/202",
            facebook_post_url="https://m.facebook.com/100/posts/202",
        ),
        policy,
        budget,
        args,
        relevant_ad_number=2,
    )

    assert first["actions"] == []
    assert second["relevant_ad_number"] == 2
    assert posted == [("ad-2", "👍")]


def test_visit_ad_landing_uses_same_context_and_closes_new_tab() -> None:
    page = LandingSourcePage()

    result = visit_ad_landing(
        page,
        "saved-post",
        cta="Learn more",
        expected_url="https://offer.example/original",
        dwell_seconds=3.0,
        timeout_ms=2_000,
    )

    assert result["status"] == "visited"
    assert result["landing_domain"] == "offer.example"
    assert result["expected_domain_match"] is True
    assert result["opened_new_page"] is True
    assert page.landing.waited == 3_000
    assert page.landing.closed is True
    assert page.unrelated.closed is False


def test_calibration_visits_landing_without_commenting(monkeypatch) -> None:
    visited: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        target_engagement,
        "view_feed_ad",
        lambda *_args: {"status": "viewing"},
    )
    monkeypatch.setattr(
        target_engagement,
        "refresh_engagement_row",
        lambda _page, row, _target: row,
    )
    monkeypatch.setattr(
        target_engagement,
        "visit_ad_landing",
        lambda _page, element_id, *, cta, expected_url, **_kwargs: (
            visited.append((element_id, cta, expected_url))
            or {"status": "visited", "landing_url": expected_url}
        ),
    )
    policy = EngagementPolicy(
        reaction_rate=0.0,
        follow_rate=0.0,
        comment_every=0,
        max_reactions=0,
        max_follows=0,
        max_comments=0,
        min_interactions=0,
    )
    args = SimpleNamespace(
        view_seconds=0.0,
        comment_template=["👍"],
        interaction_dry_run=False,
        timeout_ms=1_000,
        visit_landing=True,
        landing_view_seconds=3.0,
        landing_timeout_ms=2_000,
    )
    budget = {
        "reaction": 0,
        "follow": 0,
        "comment": 0,
        "landing_visit": 0,
        "successful": 0,
    }
    target = CalibrationTarget(
        url="https://m.facebook.com/100/posts/200",
        facebook_post_url="https://m.facebook.com/100/posts/200",
        displayed_domain="offer.example",
        landing_clean="https://offer.example/path",
        cta="Learn more",
    )

    result = facebook_calibrator._engage_row(
        object(),
        {"element_id": "saved-post"},
        target,
        policy,
        budget,
        args,
        relevant_ad_number=1,
    )

    assert result["actions"] == [
        {
            "action": "landing_visit",
            "status": "visited",
            "landing_url": "https://offer.example/path",
        }
    ]
    assert visited == [("saved-post", "Learn more", "https://offer.example/path")]
    assert budget["comment"] == 0
    assert budget["successful"] == 1


def test_calibration_opens_saved_post_without_scanning_feed(tmp_path) -> None:
    context = DirectPostContext()
    target = CalibrationTarget(
        url="https://m.facebook.com/100/posts/200",
        facebook_post_url="https://m.facebook.com/100/posts/200",
        advertiser="Saved advertiser",
    )
    policy = EngagementPolicy(
        reaction_rate=0.0,
        follow_rate=0.0,
        comment_every=5,
        max_reactions=0,
        max_follows=0,
        max_comments=1,
        min_interactions=0,
    )
    args = SimpleNamespace(
        timeout_ms=1_000,
        locate_timeout_ms=100,
        wait_after_load=0.0,
        no_screenshots=True,
        view_seconds=0.0,
        interaction_dry_run=True,
        comment_template=[],
    )
    budget = {
        "reaction": 0,
        "follow": 0,
        "comment": 0,
        "successful": 0,
        "opened": 4,
    }

    result = facebook_calibrator._calibrate_saved_ad(
        context,
        target,
        1,
        1,
        tmp_path,
        tmp_path / "events.jsonl",
        policy,
        budget,
        args,
    )

    assert result["ok"] is True
    assert result["relevant_ad_number"] == 5
    assert result["actions"] == [{"action": "comment", "status": "dry_run"}]
    assert context.page.requested_urls == ["https://m.facebook.com/100/posts/200"]


def test_calibration_retries_transient_proxy_navigation_errors(tmp_path) -> None:
    page = TransientDirectPostPage()
    context = DirectPostContext()
    context.page = page
    target = CalibrationTarget(
        url="https://m.facebook.com/100/posts/200",
        facebook_post_url="https://m.facebook.com/100/posts/200",
        advertiser="Saved advertiser",
    )
    args = SimpleNamespace(
        timeout_ms=1_000,
        locate_timeout_ms=100,
        wait_after_load=0.0,
        no_screenshots=True,
        view_seconds=0.0,
        interaction_dry_run=True,
        comment_template=[],
    )
    budget = {
        "reaction": 0,
        "follow": 0,
        "comment": 0,
        "successful": 0,
        "opened": 0,
    }

    result = facebook_calibrator._calibrate_saved_ad(
        context,
        target,
        1,
        1,
        tmp_path,
        tmp_path / "events.jsonl",
        EngagementPolicy(
            reaction_rate=0.0,
            follow_rate=0.0,
            max_reactions=0,
            max_follows=0,
            max_comments=0,
            min_interactions=0,
        ),
        budget,
        args,
    )

    assert result["ok"] is True
    assert page.requested_urls == [target.facebook_post_url] * 3
    assert page.waits[:2] == [1500, 3000]


def test_calibration_aborts_cleanly_after_exhausted_proxy_errors(tmp_path) -> None:
    page = FailedTransientDirectPostPage()
    context = DirectPostContext()
    context.page = page
    target = CalibrationTarget(
        url="https://m.facebook.com/100/posts/200",
        facebook_post_url="https://m.facebook.com/100/posts/200",
        advertiser="Saved advertiser",
    )
    args = SimpleNamespace(
        timeout_ms=1_000,
        locate_timeout_ms=100,
        wait_after_load=0.0,
        no_screenshots=True,
        view_seconds=0.0,
        interaction_dry_run=True,
        comment_template=[],
    )

    result = facebook_calibrator._calibrate_saved_ad(
        context,
        target,
        1,
        1,
        tmp_path,
        tmp_path / "events.jsonl",
        EngagementPolicy(
            reaction_rate=0.0,
            follow_rate=0.0,
            max_reactions=0,
            max_follows=0,
            max_comments=0,
            min_interactions=0,
        ),
        {
            "reaction": 0,
            "follow": 0,
            "comment": 0,
            "successful": 0,
            "opened": 0,
        },
        args,
    )

    assert result["ok"] is False
    assert result["infrastructure_error"] is True
    assert "ERR_SOCKS_CONNECTION_FAILED" in result["error"]
    assert page.requested_urls == [target.facebook_post_url] * 3
    assert page.close_calls == 0


def test_calibration_treats_closed_browser_context_as_infrastructure_error(
    tmp_path,
) -> None:
    target = CalibrationTarget(
        url="https://m.facebook.com/100/posts/200",
        facebook_post_url="https://m.facebook.com/100/posts/200",
        advertiser="Saved advertiser",
    )
    args = SimpleNamespace(
        timeout_ms=1_000,
        locate_timeout_ms=100,
        wait_after_load=0.0,
        no_screenshots=True,
        view_seconds=0.0,
        interaction_dry_run=True,
        comment_template=[],
    )

    result = facebook_calibrator._calibrate_saved_ad(
        ClosedDirectPostContext(),
        target,
        1,
        1,
        tmp_path,
        tmp_path / "events.jsonl",
        EngagementPolicy(
            reaction_rate=0.0,
            follow_rate=0.0,
            max_reactions=0,
            max_follows=0,
            max_comments=0,
            min_interactions=0,
        ),
        {
            "reaction": 0,
            "follow": 0,
            "comment": 0,
            "successful": 0,
            "opened": 0,
        },
        args,
    )

    assert result["ok"] is False
    assert result["infrastructure_error"] is True
    assert "Target page, context or browser has been closed" in result["error"]


def test_calibration_treats_direct_post_403_as_infrastructure_error(tmp_path) -> None:
    page = AccessBlockedDirectPostPage()
    context = DirectPostContext()
    context.page = page
    target = CalibrationTarget(
        url="https://m.facebook.com/100/posts/200",
        facebook_post_url="https://m.facebook.com/100/posts/200",
        advertiser="Saved advertiser",
    )
    args = SimpleNamespace(
        timeout_ms=1_000,
        locate_timeout_ms=100,
        wait_after_load=0.0,
        no_screenshots=True,
        view_seconds=0.0,
        interaction_dry_run=True,
        comment_template=[],
    )

    result = facebook_calibrator._calibrate_saved_ad(
        context,
        target,
        1,
        1,
        tmp_path,
        tmp_path / "events.jsonl",
        EngagementPolicy(
            reaction_rate=0.0,
            follow_rate=0.0,
            max_reactions=0,
            max_follows=0,
            max_comments=0,
            min_interactions=0,
        ),
        {
            "reaction": 0,
            "follow": 0,
            "comment": 0,
            "successful": 0,
            "opened": 0,
        },
        args,
    )

    assert result["ok"] is False
    assert result["infrastructure_error"] is True
    assert "Fortinet Secure DNS Service Portal" in result["error"]
    assert page.requested_urls == [target.facebook_post_url]
    assert page.close_calls == 0
