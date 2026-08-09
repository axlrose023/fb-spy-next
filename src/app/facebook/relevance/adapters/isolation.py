from __future__ import annotations

import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError

from ..evidence.policy import is_meta_host

_LOCAL_HOST_SUFFIXES = (
    ".internal",
    ".local",
    ".localhost",
    ".home",
    ".lan",
)


class NetworkGuard:
    def __init__(self, *, allow_anonymous_facebook: bool = False) -> None:
        self.meta_requests_blocked = 0
        self.private_requests_blocked = 0
        self.allow_anonymous_facebook = allow_anonymous_facebook
        self._public_cache: dict[str, bool] = {}

    def handle(self, route: Any) -> None:
        try:
            parsed = urlsplit(route.request.url)
            host = (parsed.hostname or "").casefold().rstrip(".")
            if is_meta_host(host):
                if self._allow_meta_request(route, parsed.path):
                    route.continue_()
                    return
                self.meta_requests_blocked += 1
                route.abort()
                return
            if host:
                public = self._public_cache.get(host)
                if public is None:
                    public = host_is_public(host)
                    self._public_cache[host] = public
                if not public:
                    self.private_requests_blocked += 1
                    route.abort()
                    return
            route.continue_()
        except Exception:
            try:
                route.abort()
            except Exception:
                pass

    def _allow_meta_request(self, route: Any, path: str) -> bool:
        if not self.allow_anonymous_facebook:
            return False
        if route.request.resource_type == "document":
            return True
        try:
            frame_host = (urlsplit(route.request.frame.url).hostname or "").casefold()
        except Exception:
            frame_host = ""
        return is_meta_host(frame_host) or path.casefold().endswith("/l.php")


def configure_isolated_context(context: Any, network_guard: NetworkGuard) -> None:
    context.route("**/*", network_guard.handle)
    context.add_init_script(
        """
        (() => {
          const DisabledPeerConnection = function () {
            throw new DOMException(
              "WebRTC disabled in isolated resolver",
              "NotAllowedError"
            );
          };
          Object.defineProperty(window, "RTCPeerConnection", {
            value: DisabledPeerConnection,
            configurable: false,
          });
          Object.defineProperty(window, "webkitRTCPeerConnection", {
            value: DisabledPeerConnection,
            configurable: false,
          });
        })();
        """
    )


def new_isolated_context(browser: Any) -> Any:
    options: dict[str, Any] = {
        "accept_downloads": False,
        "service_workers": "block",
    }
    profile_context = browser.contexts[0] if browser.contexts else None
    profile_page = (
        profile_context.pages[0]
        if profile_context is not None and profile_context.pages
        else None
    )
    if profile_page is not None:
        try:
            environment = profile_page.evaluate(
                """
                () => ({
                  userAgent: navigator.userAgent,
                  language: navigator.language,
                  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                  width: Math.max(320, window.innerWidth || 0),
                  height: Math.max(480, window.innerHeight || 0),
                  deviceScaleFactor: Math.max(1, window.devicePixelRatio || 1),
                  touch: Number(navigator.maxTouchPoints || 0) > 0,
                })
                """
            )
            if isinstance(environment, dict):
                options.update(_context_options(environment))
        except Exception:
            pass
    options = {key: value for key, value in options.items() if value is not None}
    try:
        return browser.new_context(**options)
    except PlaywrightError:
        return browser.new_context(
            accept_downloads=False,
            service_workers="block",
        )


def host_is_public(host: str) -> bool:
    normalized = host.casefold().rstrip(".")
    if (
        not normalized
        or normalized == "localhost"
        or normalized.endswith(_LOCAL_HOST_SUFFIXES)
    ):
        return False
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(normalized, None)}
    except OSError:
        return False
    if not addresses:
        return False
    try:
        return all(ipaddress.ip_address(address).is_global for address in addresses)
    except ValueError:
        return False


def _context_options(environment: dict[str, Any]) -> dict[str, Any]:
    user_agent = str(environment.get("userAgent") or "")
    touch = bool(environment.get("touch"))
    return {
        "user_agent": user_agent or None,
        "locale": environment.get("language"),
        "timezone_id": environment.get("timezone"),
        "viewport": {
            "width": int(environment.get("width") or 390),
            "height": int(environment.get("height") or 844),
        },
        "device_scale_factor": float(environment.get("deviceScaleFactor") or 1),
        "has_touch": touch,
        "is_mobile": bool(touch and re.search(r"android|iphone|mobile", user_agent, re.I)),
    }
