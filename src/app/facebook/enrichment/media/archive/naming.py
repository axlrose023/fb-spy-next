from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse


def archive_filename(index: int | None, domain: str | None, url: str) -> str:
    parsed = urlparse(url)
    base = domain or parsed.hostname or "landing"
    slug = re.sub(r"[^a-z0-9.-]+", "_", base.casefold()).strip("._")[:48]
    prefix = f"{index:04d}_" if index else ""
    digest = hashlib.sha1(url.encode()).hexdigest()[:8]
    return f"{prefix}{slug or 'landing'}_{digest}.zip"
