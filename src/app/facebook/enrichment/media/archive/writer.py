from __future__ import annotations

import json
import zipfile
from dataclasses import asdict
from typing import TYPE_CHECKING

from .html import rewrite_css
from .models import LandingArchiveResult
from .policy import decode_text, is_css
from .rewriter import rewrite_html

if TYPE_CHECKING:
    from .http_capture import DownloadedLanding
from .resources import build_url_path_map


def write_http_archive(
    result: LandingArchiveResult,
    download: DownloadedLanding,
) -> None:
    url_to_path = build_url_path_map(download.records, download.aliases)
    rewritten_html = rewrite_html(
        download.main_text,
        result.final_url or result.source_url,
        url_to_path,
    )
    tmp_path = result.archive_path.with_suffix(result.archive_path.suffix + ".tmp")
    with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("index.html", rewritten_html)
        archive.writestr("index.original.html", download.main_text)
        archive.writestr(
            "landing_url.txt",
            f"{result.source_url}\n{result.final_url or ''}\n",
        )
        for source_url, body in download.contents.items():
            record = download.records[source_url]
            if is_css(record.final_url, record.content_type):
                body = rewrite_css(
                    decode_text(body, record.content_type),
                    record.final_url,
                    url_to_path,
                    current_path=record.path,
                ).encode()
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
    tmp_path.replace(result.archive_path)
