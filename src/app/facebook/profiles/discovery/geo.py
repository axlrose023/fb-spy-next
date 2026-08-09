from __future__ import annotations


def normalize_country(value: str | None) -> str | None:
    if not value:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    aliases = {
        "tr": "Turkey",
        "tur": "Turkey",
        "turkey": "Turkey",
        "turkiye": "Turkey",
        "türkiye": "Turkey",
    }
    return aliases.get(normalized.casefold(), normalized)
