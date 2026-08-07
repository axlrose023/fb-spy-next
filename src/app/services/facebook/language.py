import re
import unicodedata
from typing import Any

_LANGUAGE_ALIASES = {
    "ar": "ar",
    "arabic": "ar",
    "bg": "bg",
    "bulgarian": "bg",
    "cs": "cs",
    "czech": "cs",
    "da": "da",
    "danish": "da",
    "de": "de",
    "deutsch": "de",
    "el": "el",
    "greek": "el",
    "en": "en",
    "en gb": "en",
    "en us": "en",
    "english": "en",
    "es": "es",
    "espanol": "es",
    "spanish": "es",
    "fil": "fil",
    "filipino": "fil",
    "pilipino": "fil",
    "tagalog": "fil",
    "fi": "fi",
    "finnish": "fi",
    "fr": "fr",
    "francais": "fr",
    "french": "fr",
    "german": "de",
    "hi": "hi",
    "hindi": "hi",
    "hr": "hr",
    "croatian": "hr",
    "hu": "hu",
    "hungarian": "hu",
    "id": "id",
    "indonesian": "id",
    "it": "it",
    "italian": "it",
    "ja": "ja",
    "japanese": "ja",
    "ko": "ko",
    "korean": "ko",
    "ms": "ms",
    "malay": "ms",
    "nl": "nl",
    "dutch": "nl",
    "no": "no",
    "norwegian": "no",
    "pl": "pl",
    "polish": "pl",
    "pt": "pt",
    "portuguese": "pt",
    "ro": "ro",
    "romanian": "ro",
    "ru": "ru",
    "russian": "ru",
    "sk": "sk",
    "slovak": "sk",
    "sv": "sv",
    "swedish": "sv",
    "th": "th",
    "thai": "th",
    "tr": "tr",
    "turkce": "tr",
    "turkish": "tr",
    "uk": "uk",
    "ukrainian": "uk",
    "vi": "vi",
    "vietnamese": "vi",
    "zh": "zh",
    "chinese": "zh",
}

_LANGUAGE_SEPARATOR = re.compile(r"\s*(?:[,/;|+]|\band\b)\s*", re.IGNORECASE)


def normalize_ad_language(value: Any) -> str | None:
    """Return the primary ad language as a stable ISO-style code."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    primary = _LANGUAGE_SEPARATOR.split(text, maxsplit=1)[0]
    primary = re.sub(r"\s*\([^)]*\)\s*$", "", primary)
    normalized = unicodedata.normalize("NFKD", primary)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"[-_]+", " ", normalized.casefold()).strip()
    return _LANGUAGE_ALIASES.get(normalized)


def language_from_raw_ad(raw: dict[str, Any]) -> str | None:
    direct = normalize_ad_language(raw.get("language"))
    if direct:
        return direct
    relevance = raw.get("relevance")
    if isinstance(relevance, dict):
        return normalize_ad_language(relevance.get("language"))
    return None
