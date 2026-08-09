from __future__ import annotations

import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import BrowserContext, Page, Request

from ....planning import CalibrationTarget
from ...models import OfferFunnelPolicy, OfferIdentity
from ...service import funnel_status
from ...targets import public_offer_target, target_key
from .browser import close_pages, has_offer_signal
from .forms import handle_offer_form
from .landing import open_funnel_landing
from .prelander import browse_offer_page

PIXEL_HOST_SUFFIXES = (
    "facebook.com",
    "facebook.net",
)


class OfferFunnelSession:
    """Drive relevant offer funnels in one persistent Octo browser context."""

    def __init__(
        self,
        context: BrowserContext,
        *,
        policy: OfferFunnelPolicy,
        identity: OfferIdentity | None = None,
    ) -> None:
        self.context = context
        self.policy = policy
        self.identity = identity or OfferIdentity()
        self.retained_pages: list[Page] = []
        self.submitted_targets: set[str] = set()
        self.pixel_events: list[str] = []
        self._request_handler = self._observe_request
        try:
            context.on("request", self._request_handler)
        except Exception:
            pass

    def run(
        self,
        target: CalibrationTarget,
        *,
        source_page: Page | None = None,
        element_id: str = "",
    ) -> dict[str, Any]:
        started = time.monotonic()
        result: dict[str, Any] = {
            "action": "offer_funnel",
            "status": "not_started",
            "opening": "none",
            "target": public_offer_target(target),
            "steps": [],
        }
        if not self.policy.enabled:
            return {**result, "status": "disabled"}

        opened = open_funnel_landing(
            self.context,
            self.policy,
            target,
            source_page=source_page,
            element_id=element_id,
        )
        result["steps"].append(opened.result)
        result["opening"] = str(opened.result.get("opening") or "none")
        if opened.result.get("status") != "visited":
            result["status"] = str(opened.result.get("status") or "open_failed")
            result["duration_seconds"] = round(time.monotonic() - started, 3)
            return result

        page = opened.page
        if page is None:
            raise RuntimeError("visited offer result did not provide an active page")
        if opened.result.get("cross_domain_redirect") and not has_offer_signal(page):
            result["status"] = "redirected_without_offer_signals"
            result["duration_seconds"] = round(time.monotonic() - started, 3)
            close_pages(opened.opened_pages)
            return result
        browse = browse_offer_page(page, self.policy)
        page = browse.pop("_active_page", page)
        opened.opened_pages.extend(browse.pop("_opened_pages", []))
        result["steps"].extend(browse.pop("steps", []))
        result.update(browse)

        submit_key = target_key(target, page.url)
        if result.get("form_detected"):
            form_result = handle_offer_form(
                page,
                policy=self.policy,
                identity=self.identity,
                already_submitted=submit_key in self.submitted_targets,
            )
            page = form_result.pop("_active_page", page)
            opened.opened_pages.extend(form_result.pop("_opened_pages", []))
            result["steps"].append(form_result)
            result.update(
                {
                    "form_status": form_result.get("status"),
                    "fields_filled": form_result.get("fields_filled", []),
                    "form_submitted": form_result.get("submitted", False),
                    "success_confirmed": form_result.get("success_confirmed", False),
                }
            )
            if form_result.get("submitted"):
                self.submitted_targets.add(submit_key)

        result["status"] = funnel_status(result)
        result["pixel_events"] = sorted(set(self.pixel_events))
        result["duration_seconds"] = round(time.monotonic() - started, 3)
        if result["status"] == "landing_viewed":
            close_pages(opened.opened_pages)
        else:
            self._retain(page, opened.opened_pages)
        return result

    def summary(self) -> dict[str, Any]:
        return {
            "retained_tabs": len(
                [page for page in self.retained_pages if not page.is_closed()]
            ),
            "submitted_targets": len(self.submitted_targets),
            "pixel_events": sorted(set(self.pixel_events)),
            "submit_mode": self.policy.submit_mode,
        }

    def close(self) -> None:
        try:
            self.context.remove_listener("request", self._request_handler)
        except Exception:
            pass
        close_pages(self.retained_pages)
        self.retained_pages.clear()

    def _retain(self, landing_page: Page, opened_pages: list[Page]) -> None:
        for page in [landing_page, *opened_pages]:
            if page not in self.retained_pages and not page.is_closed():
                self.retained_pages.append(page)
        limit = max(1, self.policy.max_retained_tabs)
        while len(self.retained_pages) > limit:
            oldest = self.retained_pages.pop(0)
            close_pages([oldest])

    def _observe_request(self, request: Request) -> None:
        try:
            parsed = urlsplit(request.url)
        except Exception:
            return
        host = (parsed.hostname or "").casefold()
        if not any(
            host == suffix or host.endswith(f".{suffix}")
            for suffix in PIXEL_HOST_SUFFIXES
        ):
            return
        query = parse_qs(parsed.query)
        event = str((query.get("ev") or query.get("event") or [""])[0]).strip()
        if event and event not in self.pixel_events:
            self.pixel_events.append(event[:80])
