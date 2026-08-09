from __future__ import annotations

from typing import Any

from .models import ResourceRecord


def apply_cookies(
    client: Any,
    cookies: list[dict[str, Any]] | None,
) -> None:
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


def build_url_path_map(
    records: dict[str, ResourceRecord],
    aliases: dict[str, str],
) -> dict[str, str]:
    output = {source_url: record.path for source_url, record in records.items()}
    for alias_url, source_url in aliases.items():
        record = records.get(source_url)
        if record:
            output[alias_url] = record.path
    return output
