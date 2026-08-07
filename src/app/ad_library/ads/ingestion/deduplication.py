from __future__ import annotations

from ..models import Ad
from .models import AdSource


def ad_identity(ad: Ad) -> tuple[str, str] | None:
    country = (ad.country or "").strip().lower()
    fb_ad_id = (ad.fb_ad_id or "").strip()
    if not country or not fb_ad_id:
        return None
    return country, fb_ad_id


def new_sources(
    mapped: list[tuple[AdSource, Ad]],
    existing: set[tuple[str, str]],
) -> list[tuple[AdSource, Ad]]:
    seen = set(existing)
    result: list[tuple[AdSource, Ad]] = []
    for source, ad in mapped:
        identity = ad_identity(ad)
        if identity is not None and identity in seen:
            continue
        result.append((source, ad))
        if identity is not None:
            seen.add(identity)
    return result


def explicitly_relevant(sources: list[AdSource]) -> bool:
    return all(
        isinstance(source.raw.get("relevance"), dict)
        and source.raw["relevance"].get("result") == "relevant"
        for source in sources
    )
