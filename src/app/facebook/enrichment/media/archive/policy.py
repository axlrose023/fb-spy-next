from __future__ import annotations

import hashlib
import mimetypes
import posixpath
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote, urlparse

LINK_ASSET_RELS = {
    "stylesheet",
    "preload",
    "modulepreload",
    "icon",
    "shortcut",
    "apple-touch-icon",
    "manifest",
}
LINK_ASSET_AS = {"style", "script", "font", "image", "fetch", "video", "audio"}
META_IMAGE_PROPS = {"og:image", "twitter:image", "twitter:image:src"}
URL_ASSET_ATTRS = {"src", "poster", "data-src", "data-original", "data-lazy-src"}
CSS_URL_RE = re.compile(r"""url\(\s*(['"]?)(?!data:|about:|#)(.*?)\1\s*\)""", re.I)
CSS_IMPORT_RE = re.compile(
    r"""@import\s+(?:url\(\s*)?(['"]?)(?!data:|about:|#)([^'")\s;]+)\1""",
    re.I,
)
ERROR_DOCUMENT_RE = re.compile(
    rb"(404\s+not\s+found|accessdenied|access\s+denied|<error>|<title>\s*(?:404|403|"
    rb"not\s+found|forbidden))",
    re.I,
)
HTMLISH_RESOURCE_TYPES = {"text/html", "application/xhtml+xml"}
HTML_COMPATIBLE_EXTENSIONS = {"", ".html", ".htm", ".php", ".asp", ".aspx"}


def resource_path(url: str, content_type: str, index: int) -> str:
    parsed = urlparse(url)
    name = unquote(posixpath.basename(parsed.path)).strip() or "resource"
    name = re.sub(r"[^a-zA-Z0-9._-]+", "_", name).strip("._") or "resource"
    if "." not in name:
        extension = mimetypes.guess_extension(content_type.split(";", 1)[0]) or ""
        name = f"{name}{extension}"
    digest = hashlib.sha1(url.encode()).hexdigest()[:10]
    return f"assets/{index:04d}_{digest}_{name[:80]}"


def resource_rejection_reason(
    response: Any,
    body: bytes,
) -> str | None:
    if not 200 <= response.status_code < 300:
        return f"status {response.status_code}"
    if not body:
        return "empty body"
    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
    extension = url_extension(str(response.url))
    head = body[:2048].strip().lower()
    if ERROR_DOCUMENT_RE.search(head):
        return "error document"
    if (
        extension
        and extension not in HTML_COMPATIBLE_EXTENSIONS
        and content_type in HTMLISH_RESOURCE_TYPES
        and looks_like_markup(head)
    ):
        return f"{content_type or 'html'} for {extension} resource"
    return None


def decode_text(body: bytes, content_type: str) -> str:
    charset = "utf-8"
    match = re.search(r"charset=([^;\s]+)", content_type, re.I)
    if match:
        charset = match.group(1)
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def is_css(url: str, content_type: str) -> bool:
    return "css" in content_type.casefold() or urlparse(url).path.casefold().endswith(
        ".css"
    )


def is_asset_link(attrs: Mapping[str, str | None]) -> bool:
    href = attrs.get("href")
    if not href or skip_url(href):
        return False
    relations = {part.strip().casefold() for part in (attrs.get("rel") or "").split()}
    as_type = (attrs.get("as") or "").strip().casefold()
    return bool(relations & LINK_ASSET_RELS) or as_type in LINK_ASSET_AS


def is_meta_image(attrs: Mapping[str, str | None]) -> bool:
    content = attrs.get("content")
    if not content or skip_url(content):
        return False
    prop = (attrs.get("property") or attrs.get("name") or "").strip().casefold()
    return prop in META_IMAGE_PROPS


def skip_url(url: str) -> bool:
    value = (url or "").strip().casefold()
    return not value or value.startswith(
        ("#", "data:", "blob:", "javascript:", "mailto:", "tel:")
    )


def url_extension(url: str) -> str:
    name = posixpath.basename(urlparse(url).path.casefold())
    if "." not in name:
        return ""
    suffix = "." + name.rsplit(".", 1)[-1]
    return "" if len(suffix) > 12 else suffix


def looks_like_markup(head: bytes) -> bool:
    return head.startswith((b"<html", b"<!doctype", b"<?xml", b"<error"))
