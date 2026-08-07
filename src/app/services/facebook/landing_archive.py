from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import posixpath
import re
import zipfile
from dataclasses import asdict, dataclass, field
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import httpx

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

URL_ASSET_ATTRS = {"src", "poster", "data-src", "data-original", "data-lazy-src"}
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


@dataclass(frozen=True)
class AssetRef:
    raw: str
    url: str


@dataclass
class ResourceRecord:
    url: str
    final_url: str
    path: str
    status_code: int
    content_type: str
    bytes: int


@dataclass
class LandingArchiveResult:
    archive_path: Path
    source_url: str
    final_url: str | None = None
    resources: list[ResourceRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.archive_path.is_file() and zipfile.is_zipfile(self.archive_path)


class _AssetHTMLParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.refs: list[AssetRef] = []
        self.styles: list[str] = []
        self._in_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.lower()
        attr_map = {key.lower(): value for key, value in attrs if value}
        if tag_name == "style":
            self._in_style = True
        for key, value in attr_map.items():
            if key in URL_ASSET_ATTRS:
                self._add(value)
            elif key == "srcset":
                self._add_srcset(value)
            elif key == "style":
                self.styles.append(value)
        if tag_name == "link" and _is_asset_link(attr_map):
            self._add(attr_map.get("href"))
        if tag_name == "meta" and _is_meta_image(attr_map):
            self._add(attr_map.get("content"))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "style":
            self._in_style = False

    def handle_data(self, data: str) -> None:
        if self._in_style and data:
            self.styles.append(data)

    def _add_srcset(self, value: str) -> None:
        for candidate in value.split(","):
            raw = candidate.strip().split(" ", 1)[0].strip()
            self._add(raw)

    def _add(self, raw: str | None) -> None:
        if not raw or _skip_url(raw):
            return
        absolute = urljoin(self.base_url, raw)
        if absolute.startswith(("http://", "https://")):
            self.refs.append(AssetRef(raw=raw, url=absolute))


def archive_filename(index: int | None, domain: str | None, url: str) -> str:
    parsed = urlparse(url)
    base = domain or parsed.hostname or "landing"
    slug = re.sub(r"[^a-z0-9.-]+", "_", base.lower()).strip("._")[:48] or "landing"
    prefix = f"{index:04d}_" if index else ""
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}{slug}_{digest}.zip"


def archive_landing_http(
    url: str,
    archive_path: Path,
    *,
    headers: dict[str, str] | None = None,
    cookies: list[dict] | None = None,
    timeout_seconds: float = 20.0,
    max_resources: int = 120,
    max_resource_bytes: int = 8 * 1024 * 1024,
    max_total_bytes: int = 80 * 1024 * 1024,
) -> LandingArchiveResult:
    """Create a portable zip archive for a landing URL.

    The archive contains a rewritten index.html, the original HTML, fetched
    assets, and a manifest. It intentionally stays HTTP-based so it can run in
    the production app/tasks container without a local browser install.
    """
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    result = LandingArchiveResult(archive_path=archive_path, source_url=url)
    request_headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    if headers:
        request_headers.update({k: v for k, v in headers.items() if v})

    contents: dict[str, bytes] = {}
    records: dict[str, ResourceRecord] = {}
    refs_by_base: dict[str, list[AssetRef]] = {}
    aliases: dict[str, str] = {}
    queue: list[AssetRef] = []
    total_bytes = 0

    try:
        with httpx.Client(
            headers=request_headers,
            follow_redirects=True,
            timeout=httpx.Timeout(timeout_seconds),
        ) as client:
            _apply_cookies(client, cookies)
            main_response = client.get(url)
            main_bytes = main_response.content
            total_bytes += len(main_bytes)
            result.final_url = str(main_response.url)
            main_text = _decode_text(main_bytes, main_response.headers.get("content-type", ""))
            html_refs, style_refs = _extract_html_refs(main_text, result.final_url)
            refs_by_base["index.html"] = _dedupe_refs(html_refs + style_refs)
            queue.extend(html_refs)
            queue.extend(style_refs)

            seen: set[str] = set()
            while queue and len(records) < max_resources and total_bytes < max_total_bytes:
                ref = queue.pop(0)
                if ref.url in seen or _skip_url(ref.url):
                    continue
                seen.add(ref.url)
                try:
                    response = client.get(
                        ref.url,
                        headers={
                            "Accept": "*/*",
                            "Referer": result.final_url or url,
                        },
                    )
                    body = response.content
                except Exception as exc:
                    result.errors.append(f"{ref.url}: {exc!r}")
                    continue
                rejection = _resource_rejection_reason(response, body)
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

                final_url = str(response.url)
                content_type = response.headers.get("content-type", "").split(";", 1)[0]
                path = _resource_path(final_url, content_type, len(records) + 1)
                record = ResourceRecord(
                    url=ref.url,
                    final_url=final_url,
                    path=path,
                    status_code=response.status_code,
                    content_type=content_type,
                    bytes=len(body),
                )
                records[ref.url] = record
                aliases[ref.url] = ref.url
                aliases[final_url] = ref.url
                contents[ref.url] = body
                total_bytes += len(body)

                if _is_css(final_url, content_type):
                    css_text = _decode_text(body, response.headers.get("content-type", ""))
                    css_refs = _extract_css_refs(css_text, final_url)
                    refs_by_base[path] = css_refs
                    queue.extend(css_refs)

        result.resources = list(records.values())
        url_to_path = _build_url_path_map(records, aliases)
        rewritten_html = _rewrite_html(main_text, result.final_url, url_to_path)

        tmp_path = archive_path.with_suffix(archive_path.suffix + ".tmp")
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("index.html", rewritten_html)
            archive.writestr("index.original.html", main_text)
            archive.writestr("landing_url.txt", f"{url}\n{result.final_url or ''}\n")
            for source_url, body in contents.items():
                record = records[source_url]
                if _is_css(record.final_url, record.content_type):
                    css = _decode_text(body, record.content_type)
                    css = _rewrite_css(
                        css,
                        record.final_url,
                        url_to_path,
                        current_path=record.path,
                    )
                    archive.writestr(record.path, css)
                else:
                    archive.writestr(record.path, body)
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "format_version": 2,
                        "capture_source": "http",
                        "offline_entrypoint": "index.html",
                        "source_url": result.source_url,
                        "final_url": result.final_url,
                        "resources": [asdict(item) for item in result.resources],
                        "errors": result.errors,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        tmp_path.replace(archive_path)
    except Exception as exc:
        result.errors.append(repr(exc))
        logger.exception("Landing archive failed url=%s path=%s", url, archive_path)
        if archive_path.exists():
            archive_path.unlink(missing_ok=True)
    return result


def archive_landing_page_from_browser(
    page,
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
    """Create a landing archive from the already-opened browser page.

    Live collection reaches the landing through Octo, so the browser state is
    the source of truth for cloaked pages. HTTP fetching is kept only as a
    fallback if CDP/browser capture fails.
    """
    archive_path = (
        run_dir
        / "landing_archives"
        / archive_filename(index=source_index, domain=domain, url=url)
    )
    if wait_until_ready:
        wait_for_landing_page_ready(page, timeout_seconds=timeout_seconds)
    fallback_screenshot = _read_screenshot(fallback_screenshot_path)
    result = archive_landing_browser(
        page,
        url,
        archive_path,
        fallback_screenshot=fallback_screenshot,
    )
    if result.ok:
        return archive_path.relative_to(run_dir).as_posix()

    headers: dict[str, str] = {}
    cookies: list[dict] = []
    try:
        headers["User-Agent"] = page.evaluate("() => navigator.userAgent")
    except Exception:
        pass
    try:
        cookies = page.context.cookies([url])
    except Exception:
        pass

    result = archive_landing_http(
        url,
        archive_path,
        headers=headers,
        cookies=cookies,
        timeout_seconds=timeout_seconds,
        max_resources=max_resources,
    )
    if result.ok:
        _append_browser_artifacts(
            page,
            archive_path,
            fallback_screenshot=fallback_screenshot,
        )
        return archive_path.relative_to(run_dir).as_posix()
    return None


def save_landing_screenshot_from_browser(
    page,
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
        / landing_screenshot_filename(index=source_index, domain=domain, url=url)
    )
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        screenshot_timeout_ms = min(
            15000,
            max(7000, round(timeout_seconds * 1000)),
        )
        page.screenshot(
            path=str(screenshot_path),
            full_page=True,
            timeout=screenshot_timeout_ms,
        )
    except Exception:
        logger.exception("Landing screenshot failed url=%s path=%s", url, screenshot_path)
        screenshot_path.unlink(missing_ok=True)
        return None
    return screenshot_path.relative_to(run_dir).as_posix()


def landing_screenshot_filename(index: int | None, domain: str | None, url: str) -> str:
    return archive_filename(index=index, domain=domain, url=url).replace(
        ".zip",
        "_loaded.png",
    )


def wait_for_landing_page_ready(page, *, timeout_seconds: float = 20.0) -> None:
    timeout_ms = max(1000, int(timeout_seconds * 1000))
    try:
        page.wait_for_load_state("domcontentloaded", timeout=min(timeout_ms, 12000))
    except Exception:
        pass
    try:
        page.wait_for_load_state("load", timeout=min(timeout_ms, 5000))
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


def archive_landing_browser(
    page,
    url: str,
    archive_path: Path,
    *,
    fallback_screenshot: bytes | None = None,
) -> LandingArchiveResult:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    result = LandingArchiveResult(archive_path=archive_path, source_url=url)
    artifacts: list[dict[str, str | int]] = []
    errors: list[str] = []

    final_url = _page_url(page) or url
    result.final_url = final_url

    html = ""
    try:
        html = page.content()
    except Exception as exc:
        errors.append(f"page.content: {exc!r}")

    user_agent = None
    try:
        user_agent = page.evaluate("() => navigator.userAgent")
    except Exception:
        pass

    title = None
    try:
        title = page.title()
    except Exception:
        pass

    screenshot = fallback_screenshot
    if screenshot is None:
        try:
            screenshot = page.screenshot(full_page=True, timeout=15000)
        except Exception as exc:
            errors.append(f"screenshot: {exc!r}")
    if screenshot is not None:
        artifacts.append({"path": "browser/screenshot_loaded.png", "bytes": len(screenshot)})

    mhtml = None
    try:
        session = page.context.new_cdp_session(page)
        snapshot = session.send("Page.captureSnapshot", {"format": "mhtml"})
        data = snapshot.get("data")
        if data:
            mhtml = str(data)
            artifacts.append({"path": "browser/page.mhtml", "bytes": len(mhtml.encode())})
    except Exception as exc:
        errors.append(f"mhtml: {exc!r}")

    if not html and not mhtml and screenshot is None:
        result.errors.extend(errors or ["browser capture produced no artifacts"])
        return result

    index_html = _offline_browser_index(
        final_url=final_url,
        title=title,
        has_screenshot=screenshot is not None,
        has_mhtml=bool(mhtml),
        has_dom=bool(html),
    )
    tmp_path = archive_path.with_suffix(archive_path.suffix + ".tmp")
    try:
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("index.html", index_html)
            artifacts.append({"path": "index.html", "bytes": len(index_html.encode())})
            if html:
                archive.writestr("index.original.html", html)
                archive.writestr("browser/dom.html", html)
                artifacts.append({"path": "index.original.html", "bytes": len(html.encode())})
                artifacts.append({"path": "browser/dom.html", "bytes": len(html.encode())})
            archive.writestr("landing_url.txt", f"{url}\n{final_url}\n")
            if screenshot is not None:
                archive.writestr("browser/screenshot_loaded.png", screenshot)
            if mhtml:
                archive.writestr("browser/page.mhtml", mhtml)
            result.errors.extend(errors)
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
        tmp_path.replace(archive_path)
    except Exception as exc:
        result.errors.append(repr(exc))
        logger.exception("Browser landing archive failed url=%s path=%s", url, archive_path)
        tmp_path.unlink(missing_ok=True)
        archive_path.unlink(missing_ok=True)
    return result


def _append_browser_artifacts(
    page,
    archive_path: Path,
    *,
    fallback_screenshot: bytes | None = None,
) -> None:
    try:
        with zipfile.ZipFile(archive_path, "a", compression=zipfile.ZIP_DEFLATED) as archive:
            try:
                archive.writestr("browser/dom.html", page.content())
            except Exception:
                pass
            screenshot = fallback_screenshot
            if screenshot is None:
                try:
                    screenshot = page.screenshot(full_page=True, timeout=15000)
                except Exception:
                    pass
            if screenshot is not None:
                archive.writestr("browser/screenshot_loaded.png", screenshot)
            try:
                session = page.context.new_cdp_session(page)
                snapshot = session.send("Page.captureSnapshot", {"format": "mhtml"})
                data = snapshot.get("data")
                if data:
                    archive.writestr("browser/page.mhtml", data)
            except Exception:
                pass
    except Exception:
        logger.exception("Failed to append browser artifacts to %s", archive_path)


def _read_screenshot(path: Path | None) -> bytes | None:
    if path is None:
        return None
    try:
        payload = path.read_bytes()
    except OSError:
        return None
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    return payload


def _page_url(page) -> str | None:
    try:
        value = page.url
    except Exception:
        return None
    if value and value.startswith(("http://", "https://")):
        return value
    return None


def _offline_browser_index(
    *,
    final_url: str,
    title: str | None,
    has_screenshot: bool,
    has_mhtml: bool,
    has_dom: bool,
) -> str:
    safe_title = escape(title or "Landing page snapshot")
    safe_url = escape(final_url, quote=True)
    links: list[str] = []
    if has_mhtml:
        links.append('<a href="browser/page.mhtml">Open complete MHTML snapshot</a>')
    if has_dom:
        links.append('<a href="browser/dom.html">Open captured DOM</a>')
    if final_url:
        links.append(
            f'<a href="{safe_url}" rel="noreferrer">Open original URL</a>'
        )
    navigation = "".join(links)
    if has_screenshot:
        preview = (
            '<img src="browser/screenshot_loaded.png" '
            'alt="Browser-rendered landing page snapshot">'
        )
    else:
        preview = "<p>No screenshot was available for this capture.</p>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{safe_title}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: #f4f6f5; color: #18211d; font: 14px/1.5 Arial, sans-serif; }}
    header {{ padding: 18px 22px; background: #fff; border-bottom: 1px solid #dfe5e2; }}
    h1 {{ margin: 0 0 6px; font-size: 18px; }}
    p {{ margin: 0; color: #5d6963; overflow-wrap: anywhere; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 14px; margin-top: 12px; }}
    a {{ color: #087a55; }}
    main {{ max-width: 1440px; margin: 0 auto; padding: 20px; }}
    img {{ display: block; width: 100%; height: auto; background: #fff; border: 1px solid #dfe5e2; }}
  </style>
</head>
<body>
  <header>
    <h1>{safe_title}</h1>
    <p>{safe_url}</p>
    <nav>{navigation}</nav>
  </header>
  <main>{preview}</main>
</body>
</html>
"""


def _extract_html_refs(html: str, base_url: str) -> tuple[list[AssetRef], list[AssetRef]]:
    parser = _AssetHTMLParser(base_url)
    parser.feed(html)
    style_refs: list[AssetRef] = []
    for css in parser.styles:
        style_refs.extend(_extract_css_refs(css, base_url))
    return _dedupe_refs(parser.refs), _dedupe_refs(style_refs)


def _extract_css_refs(css: str, base_url: str) -> list[AssetRef]:
    refs: list[AssetRef] = []
    for pattern in (CSS_URL_RE, CSS_IMPORT_RE):
        for match in pattern.finditer(css):
            raw = match.group(2).strip()
            if raw and not _skip_url(raw):
                refs.append(AssetRef(raw=raw, url=urljoin(base_url, raw)))
    return _dedupe_refs(refs)


def _dedupe_refs(refs: list[AssetRef]) -> list[AssetRef]:
    seen: set[tuple[str, str]] = set()
    out: list[AssetRef] = []
    for ref in refs:
        key = (ref.raw, ref.url)
        if key not in seen:
            seen.add(key)
            out.append(ref)
    return out


def _rewrite_html(html: str, base_url: str, url_to_path: dict[str, str]) -> str:
    rewriter = _HTMLRewriter(base_url, url_to_path)
    try:
        rewriter.feed(html)
        rewriter.close()
        return rewriter.html
    except Exception:
        logger.exception("HTML rewrite failed for %s", base_url)
        return html


class _HTMLRewriter(HTMLParser):
    def __init__(self, base_url: str, url_to_path: dict[str, str]) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.url_to_path = url_to_path
        self.parts: list[str] = []
        self._in_style = False
        self._in_script = False

    @property
    def html(self) -> str:
        return "".join(self.parts)

    def handle_decl(self, decl: str) -> None:
        self.parts.append(f"<!{decl}>")

    def handle_comment(self, data: str) -> None:
        self.parts.append(f"<!--{data}-->")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.lower()
        if tag_name == "style":
            self._in_style = True
        elif tag_name == "script":
            self._in_script = True
        self.parts.append(self._format_tag(tag, attrs, self_closing=False))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.parts.append(self._format_tag(tag, attrs, self_closing=True))

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name == "style":
            self._in_style = False
        elif tag_name == "script":
            self._in_script = False
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.parts.append(_rewrite_css(data, self.base_url, self.url_to_path))
        elif self._in_script:
            self.parts.append(data)
        else:
            self.parts.append(escape(data, quote=False))

    def _format_tag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
        *,
        self_closing: bool,
    ) -> str:
        rewritten = self._rewrite_attrs(tag.lower(), attrs)
        attr_text = "".join(
            f" {name}" if value is None else f' {name}="{escape(value, quote=True)}"'
            for name, value in rewritten
        )
        suffix = " /" if self_closing else ""
        return f"<{tag}{attr_text}{suffix}>"

    def _rewrite_attrs(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> list[tuple[str, str | None]]:
        attr_map = {key.lower(): value for key, value in attrs if value is not None}
        out: list[tuple[str, str | None]] = []
        for key, value in attrs:
            if value is None:
                out.append((key, value))
                continue
            lower_key = key.lower()
            if lower_key in URL_ASSET_ATTRS:
                value = self._local_url(value)
            elif lower_key == "srcset":
                value = self._rewrite_srcset(value)
            elif lower_key == "style":
                value = _rewrite_css(value, self.base_url, self.url_to_path)
            elif lower_key == "href" and tag == "link" and _is_asset_link(attr_map):
                value = self._local_url(value)
            elif lower_key == "content" and tag == "meta" and _is_meta_image(attr_map):
                value = self._local_url(value)
            out.append((key, value))
        return out

    def _local_url(self, value: str) -> str:
        if _skip_url(value):
            return value
        absolute = urljoin(self.base_url, value)
        return self.url_to_path.get(absolute) or self.url_to_path.get(value) or value

    def _rewrite_srcset(self, value: str) -> str:
        out: list[str] = []
        for candidate in value.split(","):
            bits = candidate.strip().split()
            if not bits:
                continue
            bits[0] = self._local_url(bits[0])
            out.append(" ".join(bits))
        return ", ".join(out)


def _rewrite_css(
    text: str,
    base_url: str,
    url_to_path: dict[str, str],
    *,
    current_path: str = "index.html",
) -> str:
    current_dir = posixpath.dirname(current_path)

    def local(raw: str) -> str | None:
        target = url_to_path.get(urljoin(base_url, raw)) or url_to_path.get(raw)
        if not target:
            return None
        local = posixpath.relpath(target, current_dir) if current_dir else target
        return local

    def replace_url(match: re.Match) -> str:
        quote = match.group(1) or ""
        raw = match.group(2).strip()
        rewritten = local(raw)
        if not rewritten:
            return match.group(0)
        return f"url({quote}{rewritten}{quote})"

    def replace_import(match: re.Match) -> str:
        quote = match.group(1) or ""
        raw = match.group(2).strip()
        rewritten = local(raw)
        if not rewritten:
            return match.group(0)
        return match.group(0).replace(raw, rewritten).replace(
            quote + raw + quote,
            quote + rewritten + quote,
        )

    text = CSS_URL_RE.sub(replace_url, text)
    text = CSS_IMPORT_RE.sub(replace_import, text)
    return text


def _build_url_path_map(
    records: dict[str, ResourceRecord],
    aliases: dict[str, str],
) -> dict[str, str]:
    out = {source_url: record.path for source_url, record in records.items()}
    for alias_url, source_url in aliases.items():
        record = records.get(source_url)
        if record:
            out[alias_url] = record.path
    return out


def _apply_cookies(client: httpx.Client, cookies: list[dict] | None) -> None:
    for cookie in cookies or []:
        name = cookie.get("name")
        value = cookie.get("value")
        if not name or value is None:
            continue
        domain = cookie.get("domain") or ""
        path = cookie.get("path") or "/"
        try:
            client.cookies.set(name, value, domain=domain, path=path)
        except Exception:
            client.cookies.set(name, value)


def _resource_path(url: str, content_type: str, index: int) -> str:
    parsed = urlparse(url)
    name = unquote(posixpath.basename(parsed.path)).strip() or "resource"
    name = re.sub(r"[^a-zA-Z0-9._-]+", "_", name).strip("._") or "resource"
    if "." not in name:
        ext = mimetypes.guess_extension(content_type.split(";", 1)[0]) or ""
        name = f"{name}{ext}"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    return f"assets/{index:04d}_{digest}_{name[:80]}"


def _resource_rejection_reason(response: httpx.Response, body: bytes) -> str | None:
    """Return why a fetched asset should not be treated as a saved resource."""
    if not 200 <= response.status_code < 300:
        return f"status {response.status_code}"
    if not body:
        return "empty body"

    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
    final_url = str(response.url)
    extension = _url_extension(final_url)
    head = body[:2048].strip().lower()

    if ERROR_DOCUMENT_RE.search(head):
        return "error document"
    if (
        extension
        and extension not in HTML_COMPATIBLE_EXTENSIONS
        and content_type in HTMLISH_RESOURCE_TYPES
        and _looks_like_markup(head)
    ):
        return f"{content_type or 'html'} for {extension} resource"
    return None


def _url_extension(url: str) -> str:
    path = urlparse(url).path.lower()
    name = posixpath.basename(path)
    if "." not in name:
        return ""
    suffix = "." + name.rsplit(".", 1)[-1]
    if len(suffix) > 12:
        return ""
    return suffix


def _looks_like_markup(head: bytes) -> bool:
    return head.startswith((b"<html", b"<!doctype", b"<?xml", b"<error"))


def _decode_text(body: bytes, content_type: str) -> str:
    charset = "utf-8"
    match = re.search(r"charset=([^;\s]+)", content_type, re.I)
    if match:
        charset = match.group(1)
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _is_css(url: str, content_type: str) -> bool:
    return "css" in content_type.lower() or urlparse(url).path.lower().endswith(".css")


def _is_asset_link(attrs: dict[str, str | None]) -> bool:
    href = attrs.get("href")
    if not href or _skip_url(href):
        return False
    rels = {part.strip().lower() for part in (attrs.get("rel") or "").split()}
    as_type = (attrs.get("as") or "").strip().lower()
    return bool(rels & LINK_ASSET_RELS) or as_type in LINK_ASSET_AS


def _is_meta_image(attrs: dict[str, str | None]) -> bool:
    content = attrs.get("content")
    if not content or _skip_url(content):
        return False
    prop = (attrs.get("property") or attrs.get("name") or "").strip().lower()
    return prop in META_IMAGE_PROPS


def _skip_url(url: str) -> bool:
    value = (url or "").strip().lower()
    return (
        not value
        or value.startswith(("#", "data:", "blob:", "javascript:", "mailto:", "tel:"))
    )
