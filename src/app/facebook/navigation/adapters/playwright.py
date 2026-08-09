from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

TRANSIENT_NAVIGATION_ERRORS = (
    "ERR_SOCKS_CONNECTION_FAILED",
    "ERR_PROXY_CONNECTION_FAILED",
    "ERR_NETWORK_CHANGED",
    "ERR_CONNECTION_RESET",
    "ERR_CONNECTION_CLOSED",
    "ERR_TIMED_OUT",
)
PROXY_CERTIFICATE_AUTHORITY_ERROR = "ERR_CERT_AUTHORITY_INVALID"

FACEBOOK_LOGIN_PROBE_JS = """
() => {
  const path = window.location.pathname.toLowerCase();
  const authPath = (
    path.startsWith("/login")
    || path.startsWith("/checkpoint")
    || path.startsWith("/recover")
    || path.startsWith("/unified/login")
  );
  const password = document.querySelector('input[type="password"]');
  const identity = document.querySelector(
    'input[name="email"], input[type="email"], input[name="phone"]'
  );
  return authPath || Boolean(password && identity);
}
"""


def is_facebook_feed_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = parsed.netloc.lower()
    return host.endswith("facebook.com") and parsed.path in ("", "/", "/home.php")


def facebook_login_required(page: Any) -> bool:
    """Distinguish a logged-out Facebook page from an empty authenticated feed."""
    try:
        return bool(page.evaluate(FACEBOOK_LOGIN_PROBE_JS))
    except Exception:
        return False


def is_transient_navigation_error(error: BaseException) -> bool:
    return any(code in str(error) for code in TRANSIENT_NAVIGATION_ERRORS)


def ignore_proxy_certificate_errors(page: Any) -> bool:
    """Allow an Octo proxy's untrusted CA only in the current CDP session."""
    try:
        session = page.context.new_cdp_session(page)
        session.send("Security.setIgnoreCertificateErrors", {"ignore": True})
    except Exception as exc:
        print(
            f"[navigation] could not accept proxy certificate authority: {exc}",
            flush=True,
        )
        return False
    return True


def goto_with_retry(
    page: Any,
    url: str,
    *,
    timeout: int,
    attempts: int = 5,
    base_delay_seconds: float = 1.5,
    sleeper: Callable[[float], None] | None = None,
    certificate_handler: Callable[[Any], bool] | None = None,
) -> Any:
    """Retry navigation while an Octo profile's proxy is still coming up."""
    active_sleeper = sleeper or time.sleep
    active_certificate_handler = certificate_handler or ignore_proxy_certificate_errors
    total_attempts = max(1, attempts)
    ignored_proxy_certificate_error = False
    for attempt in range(1, total_attempts + 1):
        try:
            return page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=timeout,
            )
        except Exception as exc:
            if (
                not ignored_proxy_certificate_error
                and PROXY_CERTIFICATE_AUTHORITY_ERROR in str(exc)
                and active_certificate_handler(page)
            ):
                ignored_proxy_certificate_error = True
                print(
                    "[navigation retry] accepted proxy certificate authority "
                    f"for this browser session; attempt={attempt}/{total_attempts}",
                    flush=True,
                )
                continue
            transient = isinstance(exc, PlaywrightTimeoutError) or (
                is_transient_navigation_error(exc)
            )
            if not transient or attempt >= total_attempts:
                raise
            delay = base_delay_seconds * attempt
            print(
                f"[navigation retry] attempt={attempt}/{total_attempts} "
                f"delay={delay:.1f}s error={exc}",
                flush=True,
            )
            active_sleeper(delay)
    raise RuntimeError("navigation retries exhausted")


def recover_facebook_feed(
    page: Any,
    feed_url: str = "https://m.facebook.com/",
    *,
    sleeper: Callable[[float], None] | None = None,
) -> None:
    active_sleeper = sleeper or time.sleep
    try:
        if not is_facebook_feed_url(page.url):
            goto_with_retry(
                page,
                feed_url,
                timeout=12000,
                attempts=3,
                sleeper=active_sleeper,
            )
            active_sleeper(3)
    except Exception:
        pass
