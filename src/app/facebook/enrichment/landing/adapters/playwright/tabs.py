from __future__ import annotations

from typing import Any


def close_landing_tabs(ctx: Any, keep: Any | None = None) -> None:
    """Close every tab except the driven feed page and DevTools."""
    for page in list(ctx.pages):
        try:
            if keep is not None and page == keep:
                continue
            if page.url.startswith("devtools"):
                continue
            page.close()
        except Exception:
            pass


def neutralize_profile_pages(page: Any, ctx: Any) -> None:
    """Leave the persistent profile without a visible ad or playing media."""
    try:
        page.evaluate(
            """
            () => {
              for (const video of document.querySelectorAll("video")) {
                try { video.pause(); video.muted = true; } catch (_) {}
              }
            }
            """
        )
    except Exception:
        pass
    close_landing_tabs(ctx, keep=page)
    try:
        page.goto("about:blank", wait_until="commit", timeout=5000)
    except Exception:
        pass
