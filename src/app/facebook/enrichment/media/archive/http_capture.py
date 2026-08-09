from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .html import extract_css_refs, extract_html_refs
from .models import AssetRef, LandingArchiveResult, ResourceRecord
from .policy import (
    decode_text,
    is_css,
    resource_path,
    resource_rejection_reason,
    skip_url,
)
from .resources import apply_cookies
from .writer import write_http_archive

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@dataclass(slots=True)
class DownloadedLanding:
    main_text: str = ""
    contents: dict[str, bytes] = field(default_factory=dict)
    records: dict[str, ResourceRecord] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)


def archive_landing_http(
    url: str,
    archive_path: Path,
    *,
    headers: dict[str, str] | None = None,
    cookies: list[dict[str, Any]] | None = None,
    timeout_seconds: float = 20.0,
    max_resources: int = 120,
    max_resource_bytes: int = 8 * 1024 * 1024,
    max_total_bytes: int = 80 * 1024 * 1024,
) -> LandingArchiveResult:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    result = LandingArchiveResult(archive_path=archive_path, source_url=url)
    try:
        download = _download_landing(
            url,
            result,
            headers=headers,
            cookies=cookies,
            timeout_seconds=timeout_seconds,
            max_resources=max_resources,
            max_resource_bytes=max_resource_bytes,
            max_total_bytes=max_total_bytes,
        )
        result.resources = list(download.records.values())
        write_http_archive(result, download)
    except Exception as exc:
        result.errors.append(repr(exc))
        logger.exception("Landing archive failed url=%s path=%s", url, archive_path)
        archive_path.unlink(missing_ok=True)
    return result


def _download_landing(
    url: str,
    result: LandingArchiveResult,
    *,
    headers: dict[str, str] | None,
    cookies: list[dict[str, Any]] | None,
    timeout_seconds: float,
    max_resources: int,
    max_resource_bytes: int,
    max_total_bytes: int,
) -> DownloadedLanding:
    request_headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    request_headers.update(
        {key: value for key, value in (headers or {}).items() if value}
    )
    download = DownloadedLanding()
    with httpx.Client(
        headers=request_headers,
        follow_redirects=True,
        timeout=httpx.Timeout(timeout_seconds),
    ) as client:
        apply_cookies(client, cookies)
        main_response = client.get(url)
        total_bytes = len(main_response.content)
        result.final_url = str(main_response.url)
        download.main_text = decode_text(
            main_response.content,
            main_response.headers.get("content-type", ""),
        )
        html_refs, style_refs = extract_html_refs(download.main_text, result.final_url)
        queue = html_refs + style_refs
        seen: set[str] = set()
        while queue and len(download.records) < max_resources:
            if total_bytes >= max_total_bytes:
                break
            ref = queue.pop(0)
            if ref.url in seen or skip_url(ref.url):
                continue
            seen.add(ref.url)
            response, body = _fetch_resource(client, ref, result, url)
            if response is None:
                continue
            rejection = resource_rejection_reason(response, body)
            if rejection:
                result.errors.append(f"{ref.url}: skipped {rejection}")
                continue
            if len(body) > max_resource_bytes:
                result.errors.append(
                    f"{ref.url}: skipped oversized resource ({len(body)} bytes)"
                )
                continue
            if total_bytes + len(body) > max_total_bytes:
                result.errors.append(f"{ref.url}: skipped total size limit")
                continue
            record = _record_resource(ref, response, body, download)
            total_bytes += len(body)
            if is_css(record.final_url, record.content_type):
                queue.extend(
                    extract_css_refs(
                        decode_text(body, response.headers.get("content-type", "")),
                        record.final_url,
                    )
                )
    return download


def _fetch_resource(
    client: httpx.Client,
    ref: AssetRef,
    result: LandingArchiveResult,
    source_url: str,
) -> tuple[httpx.Response | None, bytes]:
    try:
        response = client.get(
            ref.url,
            headers={"Accept": "*/*", "Referer": result.final_url or source_url},
        )
        return response, response.content
    except Exception as exc:
        result.errors.append(f"{ref.url}: {exc!r}")
        return None, b""


def _record_resource(
    ref: AssetRef,
    response: httpx.Response,
    body: bytes,
    download: DownloadedLanding,
) -> ResourceRecord:
    final_url = str(response.url)
    content_type = response.headers.get("content-type", "").split(";", 1)[0]
    record = ResourceRecord(
        url=ref.url,
        final_url=final_url,
        path=resource_path(final_url, content_type, len(download.records) + 1),
        status_code=response.status_code,
        content_type=content_type,
        bytes=len(body),
    )
    download.records[ref.url] = record
    download.aliases[ref.url] = ref.url
    download.aliases[final_url] = ref.url
    download.contents[ref.url] = body
    return record
