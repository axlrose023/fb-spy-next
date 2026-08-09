from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .archive.naming import archive_filename

logger = logging.getLogger(__name__)


def save_landing_screenshot_from_browser(
    page: Any,
    run_dir: Path,
    *,
    source_index: int | None,
    domain: str | None,
    url: str,
    timeout_seconds: float = 20.0,
    wait_until_ready: bool = True,
) -> str | None:
    if wait_until_ready:
        wait_for_landing_page_ready(page, timeout_seconds=timeout_seconds)
    screenshot_path = (
        run_dir
        / "landing_screens"
        / landing_screenshot_filename(source_index, domain, url)
    )
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(
            path=str(screenshot_path),
            full_page=True,
            timeout=min(15000, max(7000, round(timeout_seconds * 1000))),
        )
    except Exception:
        logger.exception(
            "Landing screenshot failed url=%s path=%s", url, screenshot_path
        )
        screenshot_path.unlink(missing_ok=True)
        return None
    return screenshot_path.relative_to(run_dir).as_posix()


def landing_screenshot_filename(
    index: int | None,
    domain: str | None,
    url: str,
) -> str:
    return archive_filename(index=index, domain=domain, url=url).replace(
        ".zip",
        "_loaded.png",
    )


def wait_for_landing_page_ready(
    page: Any,
    *,
    timeout_seconds: float = 20.0,
) -> None:
    timeout_ms = max(1000, int(timeout_seconds * 1000))
    for state, limit in (("domcontentloaded", 12000), ("load", 5000)):
        try:
            page.wait_for_load_state(state, timeout=min(timeout_ms, limit))
        except Exception:
            pass
    try:
        page.wait_for_function(
            """() => {
                const body = document.body;
                if (!body) return false;
                const rect = body.getBoundingClientRect();
                return document.readyState !== "loading" && rect.height > 80 && rect.width > 80;
            }""",
            timeout=min(timeout_ms, 6000),
        )
    except Exception:
        pass
    try:
        page.wait_for_timeout(1200)
    except Exception:
        pass
