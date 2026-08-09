from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.facebook.calibration.adapters.playwright import navigation as calibration_nav
from app.facebook.navigation import (
    PROXY_CERTIFICATE_AUTHORITY_ERROR,
    TRANSIENT_NAVIGATION_ERRORS,
    facebook_login_required,
    goto_with_retry,
    ignore_proxy_certificate_errors,
    is_facebook_feed_url,
    is_transient_navigation_error,
    recover_facebook_feed,
)
from app.services import facebook_runner

pytestmark = pytest.mark.unit


class FlakyPage:
    def __init__(self, failures: list[Exception], *, url: str = "about:blank") -> None:
        self.failures = failures
        self.url = url
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def goto(self, url: str, **kwargs: Any) -> str:
        self.calls.append((url, kwargs))
        if self.failures:
            raise self.failures.pop(0)
        self.url = url
        return "loaded"


class FakeCDPSession:
    def __init__(self) -> None:
        self.commands: list[tuple[str, dict[str, bool]]] = []

    def send(self, method: str, params: dict[str, bool]) -> None:
        self.commands.append((method, params))


class FakeContext:
    def __init__(self) -> None:
        self.session = FakeCDPSession()

    def new_cdp_session(self, _page: Any) -> FakeCDPSession:
        return self.session


class ProxyCertificatePage(FlakyPage):
    def __init__(self) -> None:
        super().__init__([RuntimeError(PROXY_CERTIFICATE_AUTHORITY_ERROR)])
        self.context = FakeContext()


class LoginProbePage:
    def __init__(self, result: bool | Exception) -> None:
        self.result = result

    def evaluate(self, script: str) -> bool:
        assert 'input[type="password"]' in script
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_retry_policy_handles_transient_errors_and_timeout() -> None:
    page = FlakyPage(
        [
            RuntimeError("net::ERR_PROXY_CONNECTION_FAILED"),
            PlaywrightTimeoutError("Page.goto timeout"),
        ]
    )
    delays: list[float] = []

    result = goto_with_retry(
        page,
        "https://m.facebook.com/",
        timeout=20_000,
        sleeper=delays.append,
    )

    assert result == "loaded"
    assert len(page.calls) == 3
    assert delays == [1.5, 3.0]


def test_retry_policy_re_raises_non_transient_error() -> None:
    page = FlakyPage([RuntimeError("net::ERR_CERT_INVALID")])

    with pytest.raises(RuntimeError, match="ERR_CERT_INVALID"):
        goto_with_retry(
            page,
            "https://m.facebook.com/",
            timeout=20_000,
            sleeper=lambda _seconds: None,
        )

    assert len(page.calls) == 1


def test_retry_policy_accepts_proxy_certificate_once() -> None:
    page = ProxyCertificatePage()

    result = goto_with_retry(
        page,
        "https://m.facebook.com/",
        timeout=20_000,
        sleeper=lambda _seconds: None,
    )

    assert result == "loaded"
    assert page.context.session.commands == [
        ("Security.setIgnoreCertificateErrors", {"ignore": True})
    ]


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://facebook.com/", True),
        ("https://m.facebook.com/home.php", True),
        ("https://m.facebook.com/123/posts/456", False),
        ("https://example.com/", False),
    ],
)
def test_feed_url_classification(url: str, expected: bool) -> None:
    assert is_facebook_feed_url(url) is expected


def test_login_probe_is_fail_closed_for_probe_errors() -> None:
    assert facebook_login_required(LoginProbePage(True)) is True
    assert facebook_login_required(LoginProbePage(False)) is False
    assert facebook_login_required(LoginProbePage(RuntimeError("detached"))) is False


def test_feed_recovery_navigates_and_waits_after_success() -> None:
    page = FlakyPage([], url="https://m.facebook.com/123/posts/456")
    delays: list[float] = []

    recover_facebook_feed(page, sleeper=delays.append)

    assert page.url == "https://m.facebook.com/"
    assert delays == [3]


def test_feed_recovery_swallows_navigation_failure() -> None:
    page = FlakyPage([RuntimeError("permanent")], url="about:blank")

    recover_facebook_feed(page, sleeper=lambda _seconds: None)

    assert len(page.calls) == 1


def test_runner_compatibility_aliases_share_canonical_policy() -> None:
    assert facebook_runner._goto_with_retry is goto_with_retry
    assert facebook_runner._facebook_login_required is facebook_login_required
    assert (
        facebook_runner._ignore_proxy_certificate_errors
        is ignore_proxy_certificate_errors
    )
    assert facebook_runner._is_fb_feed_url is is_facebook_feed_url
    assert facebook_runner._recover_feed is recover_facebook_feed
    assert facebook_runner.TRANSIENT_NAVIGATION_ERRORS is TRANSIENT_NAVIGATION_ERRORS


def test_calibration_uses_shared_transient_navigation_policy() -> None:
    error = RuntimeError("net::ERR_CONNECTION_RESET")

    assert calibration_nav.is_transient_navigation_error is (
        is_transient_navigation_error
    )
    assert calibration_nav.TRANSIENT_NAVIGATION_ERRORS is (TRANSIENT_NAVIGATION_ERRORS)
    assert calibration_nav.is_transient_navigation_error(error) is True
