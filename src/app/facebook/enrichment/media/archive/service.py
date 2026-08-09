from __future__ import annotations

from pathlib import Path
from typing import Any

from ..screenshot import wait_for_landing_page_ready
from .browser_capture import (
    append_browser_artifacts,
    archive_landing_browser,
    read_screenshot,
)
from .http_capture import archive_landing_http
from .naming import archive_filename


def archive_landing_page_from_browser(
    page: Any,
    run_dir: Path,
    *,
    source_index: int | None,
    domain: str | None,
    url: str,
    timeout_seconds: float = 20.0,
    max_resources: int = 120,
    wait_until_ready: bool = True,
    fallback_screenshot_path: Path | None = None,
) -> str | None:
    archive_path = (
        run_dir
        / "landing_archives"
        / archive_filename(index=source_index, domain=domain, url=url)
    )
    if wait_until_ready:
        wait_for_landing_page_ready(page, timeout_seconds=timeout_seconds)
    fallback_screenshot = read_screenshot(fallback_screenshot_path)
    result = archive_landing_browser(
        page,
        url,
        archive_path,
        fallback_screenshot=fallback_screenshot,
    )
    if result.ok:
        return archive_path.relative_to(run_dir).as_posix()

    headers, cookies = _browser_request_context(page, url)
    result = archive_landing_http(
        url,
        archive_path,
        headers=headers,
        cookies=cookies,
        timeout_seconds=timeout_seconds,
        max_resources=max_resources,
    )
    if not result.ok:
        return None
    append_browser_artifacts(
        page,
        archive_path,
        fallback_screenshot=fallback_screenshot,
    )
    return archive_path.relative_to(run_dir).as_posix()


def _browser_request_context(
    page: Any,
    url: str,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    headers: dict[str, str] = {}
    cookies: list[dict[str, Any]] = []
    try:
        headers["User-Agent"] = page.evaluate("() => navigator.userAgent")
    except Exception:
        pass
    try:
        cookies = page.context.cookies([url])
    except Exception:
        pass
    return headers, cookies
