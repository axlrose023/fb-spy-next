from __future__ import annotations

import logging
from html import escape
from html.parser import HTMLParser
from urllib.parse import urljoin

from .html import rewrite_css
from .policy import URL_ASSET_ATTRS, is_asset_link, is_meta_image, skip_url

logger = logging.getLogger(__name__)


def rewrite_html(html: str, base_url: str, url_to_path: dict[str, str]) -> str:
    rewriter = HTMLRewriter(base_url, url_to_path)
    try:
        rewriter.feed(html)
        rewriter.close()
        return rewriter.html
    except Exception:
        logger.exception("HTML rewrite failed for %s", base_url)
        return html


class HTMLRewriter(HTMLParser):
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
        if tag.casefold() == "style":
            self._in_style = True
        elif tag.casefold() == "script":
            self._in_script = True
        self.parts.append(self._format_tag(tag, attrs, self_closing=False))

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.parts.append(self._format_tag(tag, attrs, self_closing=True))

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "style":
            self._in_style = False
        elif tag.casefold() == "script":
            self._in_script = False
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.parts.append(rewrite_css(data, self.base_url, self.url_to_path))
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
        rewritten = self._rewrite_attrs(tag.casefold(), attrs)
        attr_text = "".join(
            f" {name}" if value is None else f' {name}="{escape(value, quote=True)}"'
            for name, value in rewritten
        )
        return f"<{tag}{attr_text}{' /' if self_closing else ''}>"

    def _rewrite_attrs(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> list[tuple[str, str | None]]:
        attr_map: dict[str, str | None] = {
            key.casefold(): value for key, value in attrs if value is not None
        }
        output: list[tuple[str, str | None]] = []
        for key, value in attrs:
            if value is None:
                output.append((key, value))
                continue
            lower_key = key.casefold()
            if lower_key in URL_ASSET_ATTRS:
                value = self._local_url(value)
            elif lower_key == "srcset":
                value = self._rewrite_srcset(value)
            elif lower_key == "style":
                value = rewrite_css(value, self.base_url, self.url_to_path)
            elif lower_key == "href" and tag == "link" and is_asset_link(attr_map):
                value = self._local_url(value)
            elif lower_key == "content" and tag == "meta" and is_meta_image(attr_map):
                value = self._local_url(value)
            output.append((key, value))
        return output

    def _local_url(self, value: str) -> str:
        if skip_url(value):
            return value
        absolute = urljoin(self.base_url, value)
        return self.url_to_path.get(absolute) or self.url_to_path.get(value) or value

    def _rewrite_srcset(self, value: str) -> str:
        output: list[str] = []
        for candidate in value.split(","):
            bits = candidate.strip().split()
            if bits:
                bits[0] = self._local_url(bits[0])
                output.append(" ".join(bits))
        return ", ".join(output)
