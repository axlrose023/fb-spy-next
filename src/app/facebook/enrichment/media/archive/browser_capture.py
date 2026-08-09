from __future__ import annotations

import json
import logging
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .browser_index import offline_browser_index
from .models import LandingArchiveResult

logger = logging.getLogger(__name__)


def archive_landing_browser(
    page: Any,
    url: str,
    archive_path: Path,
    *,
    fallback_screenshot: bytes | None = None,
) -> LandingArchiveResult:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    result = LandingArchiveResult(archive_path=archive_path, source_url=url)
    result.final_url = page_url(page) or url
    html, user_agent, title, screenshot, mhtml, errors = _capture_artifacts(
        page,
        fallback_screenshot,
    )
    if not html and not mhtml and screenshot is None:
        result.errors.extend(errors or ["browser capture produced no artifacts"])
        return result
    result.errors.extend(errors)
    _write_browser_archive(
        result,
        html=html,
        user_agent=user_agent,
        title=title,
        screenshot=screenshot,
        mhtml=mhtml,
    )
    return result


def append_browser_artifacts(
    page: Any,
    archive_path: Path,
    *,
    fallback_screenshot: bytes | None = None,
) -> None:
    try:
        with zipfile.ZipFile(
            archive_path, "a", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            try:
                archive.writestr("browser/dom.html", page.content())
            except Exception:
                pass
            screenshot = fallback_screenshot or _capture_screenshot(page)
            if screenshot is not None:
                archive.writestr("browser/screenshot_loaded.png", screenshot)
            mhtml = _capture_mhtml(page)
            if mhtml:
                archive.writestr("browser/page.mhtml", mhtml)
    except Exception:
        logger.exception("Failed to append browser artifacts to %s", archive_path)


def read_screenshot(path: Path | None) -> bytes | None:
    if path is None:
        return None
    try:
        payload = path.read_bytes()
    except OSError:
        return None
    return payload if payload.startswith(b"\x89PNG\r\n\x1a\n") else None


def page_url(page: Any) -> str | None:
    try:
        value = page.url
    except Exception:
        return None
    return value if value and value.startswith(("http://", "https://")) else None


def _capture_artifacts(
    page: Any,
    fallback_screenshot: bytes | None,
) -> tuple[str, str | None, str | None, bytes | None, str | None, list[str]]:
    errors: list[str] = []
    html = _capture_value(page.content, "page.content", errors, "")
    user_agent = _capture_value(
        lambda: page.evaluate("() => navigator.userAgent"),
        "user_agent",
        [],
        None,
    )
    title = _capture_value(page.title, "title", [], None)
    screenshot = fallback_screenshot
    if screenshot is None:
        try:
            screenshot = page.screenshot(full_page=True, timeout=15000)
        except Exception as exc:
            errors.append(f"screenshot: {exc!r}")
    mhtml = None
    try:
        mhtml = _capture_mhtml(page)
    except Exception as exc:
        errors.append(f"mhtml: {exc!r}")
    return html, user_agent, title, screenshot, mhtml, errors


def _capture_value[T](
    call: Callable[[], T],
    label: str,
    errors: list[str],
    default: T,
) -> T:
    try:
        return call()
    except Exception as exc:
        errors.append(f"{label}: {exc!r}")
        return default


def _capture_screenshot(page: Any) -> bytes | None:
    try:
        payload = page.screenshot(full_page=True, timeout=15000)
        return payload if isinstance(payload, bytes) else None
    except Exception:
        return None


def _capture_mhtml(page: Any) -> str | None:
    session = page.context.new_cdp_session(page)
    data = session.send("Page.captureSnapshot", {"format": "mhtml"}).get("data")
    return str(data) if data else None


def _write_browser_archive(
    result: LandingArchiveResult,
    *,
    html: str,
    user_agent: str | None,
    title: str | None,
    screenshot: bytes | None,
    mhtml: str | None,
) -> None:
    index_html = offline_browser_index(
        final_url=result.final_url or result.source_url,
        title=title,
        has_screenshot=screenshot is not None,
        has_mhtml=bool(mhtml),
        has_dom=bool(html),
    )
    artifacts = _artifact_manifest(index_html, html, screenshot, mhtml)
    tmp_path = result.archive_path.with_suffix(result.archive_path.suffix + ".tmp")
    try:
        with zipfile.ZipFile(
            tmp_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            archive.writestr("index.html", index_html)
            if html:
                archive.writestr("index.original.html", html)
                archive.writestr("browser/dom.html", html)
            archive.writestr(
                "landing_url.txt",
                f"{result.source_url}\n{result.final_url or ''}\n",
            )
            if screenshot is not None:
                archive.writestr("browser/screenshot_loaded.png", screenshot)
            if mhtml:
                archive.writestr("browser/page.mhtml", mhtml)
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "format_version": 2,
                        "capture_source": "browser",
                        "offline_entrypoint": "index.html",
                        "source_url": result.source_url,
                        "final_url": result.final_url,
                        "title": title,
                        "user_agent": user_agent,
                        "resources": [],
                        "artifacts": artifacts,
                        "errors": result.errors,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        tmp_path.replace(result.archive_path)
    except Exception as exc:
        result.errors.append(repr(exc))
        logger.exception(
            "Browser landing archive failed url=%s path=%s",
            result.source_url,
            result.archive_path,
        )
        tmp_path.unlink(missing_ok=True)
        result.archive_path.unlink(missing_ok=True)


def _artifact_manifest(
    index_html: str,
    html: str,
    screenshot: bytes | None,
    mhtml: str | None,
) -> list[dict[str, str | int]]:
    artifacts: list[dict[str, str | int]] = [
        {"path": "index.html", "bytes": len(index_html.encode())}
    ]
    if html:
        size = len(html.encode())
        artifacts.extend(
            [
                {"path": "index.original.html", "bytes": size},
                {"path": "browser/dom.html", "bytes": size},
            ]
        )
    if screenshot is not None:
        artifacts.append(
            {"path": "browser/screenshot_loaded.png", "bytes": len(screenshot)}
        )
    if mhtml:
        artifacts.append({"path": "browser/page.mhtml", "bytes": len(mhtml.encode())})
    return artifacts
