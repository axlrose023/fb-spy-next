from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse


def parse_landing(url: str) -> tuple[str, dict[str, str], str | None]:
    """Return the stable URL, tracking values and best ad-level identifier."""
    parsed = urlparse(url)
    clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    query = parse_qs(parsed.query)
    tracking = {
        key: values[0]
        for key, values in query.items()
        if key.startswith("utm_") or key == "fbclid"
    }

    def first_numeric(keys: tuple[str, ...]) -> str | None:
        for key in keys:
            for value in query.get(key, []):
                match = re.search(r"\d{10,}", value)
                if match:
                    return match.group(0)
        return None

    ad_id = first_numeric(("ad_id", "adid", "fb_ad_id", "utm_content"))
    if not ad_id:
        match = re.search(
            r"(?:[?&]|%26)(?:ad[_-]?id|adid|fb_ad_id|sub5)=(\d{10,})",
            url,
        )
        if match:
            ad_id = match.group(1)
    if not ad_id:
        ad_id = first_numeric(("utm_term", "utm_id"))
    return clean, tracking, ad_id


def external_landing_url(url: str | None) -> str | None:
    """Return an external URL, including a target wrapped by Facebook l.php."""
    if not url or not url.startswith(("http://", "https://")):
        return None
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if not host.endswith("facebook.com"):
            return url
        if parsed.path.endswith("/l.php"):
            target = parse_qs(parsed.query).get("u", [None])[0]
            if target and target.startswith(("http://", "https://")):
                target_host = (urlparse(target).hostname or "").lower()
                if not target_host.endswith("facebook.com"):
                    return target
    except Exception:
        pass
    return None
