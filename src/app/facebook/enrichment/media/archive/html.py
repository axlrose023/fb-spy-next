from __future__ import annotations

import posixpath
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from .models import AssetRef
from .policy import (
    CSS_IMPORT_RE,
    CSS_URL_RE,
    URL_ASSET_ATTRS,
    is_asset_link,
    is_meta_image,
    skip_url,
)


class AssetHTMLParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.refs: list[AssetRef] = []
        self.styles: list[str] = []
        self._in_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.casefold()
        attr_map = {key.casefold(): value for key, value in attrs if value}
        if tag_name == "style":
            self._in_style = True
        for key, value in attr_map.items():
            if key in URL_ASSET_ATTRS:
                self._add(value)
            elif key == "srcset":
                self._add_srcset(value)
            elif key == "style":
                self.styles.append(value)
        if tag_name == "link" and is_asset_link(attr_map):
            self._add(attr_map.get("href"))
        if tag_name == "meta" and is_meta_image(attr_map):
            self._add(attr_map.get("content"))

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "style":
            self._in_style = False

    def handle_data(self, data: str) -> None:
        if self._in_style and data:
            self.styles.append(data)

    def _add_srcset(self, value: str) -> None:
        for candidate in value.split(","):
            self._add(candidate.strip().split(" ", 1)[0].strip())

    def _add(self, raw: str | None) -> None:
        if not raw or skip_url(raw):
            return
        absolute = urljoin(self.base_url, raw)
        if absolute.startswith(("http://", "https://")):
            self.refs.append(AssetRef(raw=raw, url=absolute))


def extract_html_refs(
    html: str,
    base_url: str,
) -> tuple[list[AssetRef], list[AssetRef]]:
    parser = AssetHTMLParser(base_url)
    parser.feed(html)
    style_refs = [
        ref for css in parser.styles for ref in extract_css_refs(css, base_url)
    ]
    return dedupe_refs(parser.refs), dedupe_refs(style_refs)


def extract_css_refs(css: str, base_url: str) -> list[AssetRef]:
    refs: list[AssetRef] = []
    for pattern in (CSS_URL_RE, CSS_IMPORT_RE):
        for match in pattern.finditer(css):
            raw = match.group(2).strip()
            if raw and not skip_url(raw):
                refs.append(AssetRef(raw=raw, url=urljoin(base_url, raw)))
    return dedupe_refs(refs)


def dedupe_refs(refs: list[AssetRef]) -> list[AssetRef]:
    seen: set[tuple[str, str]] = set()
    output: list[AssetRef] = []
    for ref in refs:
        key = (ref.raw, ref.url)
        if key not in seen:
            seen.add(key)
            output.append(ref)
    return output


def rewrite_css(
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
        return posixpath.relpath(target, current_dir) if current_dir else target

    def replace_url(match: re.Match[str]) -> str:
        quote = match.group(1) or ""
        rewritten = local(match.group(2).strip())
        return f"url({quote}{rewritten}{quote})" if rewritten else match.group(0)

    def replace_import(match: re.Match[str]) -> str:
        quote = match.group(1) or ""
        raw = match.group(2).strip()
        rewritten = local(raw)
        if not rewritten:
            return match.group(0)
        return match.group(0).replace(
            quote + raw + quote,
            quote + rewritten + quote,
        )

    return CSS_IMPORT_RE.sub(replace_import, CSS_URL_RE.sub(replace_url, text))
