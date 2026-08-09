from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import OfferIdentity


def load_offer_identity(
    path: Path | None,
    *,
    profile_uuid: str = "",
    country: str | None = None,
) -> OfferIdentity:
    if path is None:
        return OfferIdentity()
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Offer identity JSON must contain an object")
    selected = select_identity_payload(
        payload,
        profile_uuid=profile_uuid,
        country=country,
    )
    return OfferIdentity(
        first_name=str(selected.get("first_name") or "").strip(),
        last_name=str(selected.get("last_name") or "").strip(),
        email=str(selected.get("email") or "").strip(),
        phone=str(selected.get("phone") or "").strip(),
        country_code=str(selected.get("country_code") or "").strip().upper(),
    )


def select_identity_payload(
    payload: dict[str, Any],
    *,
    profile_uuid: str,
    country: str | None,
) -> dict[str, Any]:
    if any(key in payload for key in ("first_name", "email", "phone")):
        return payload
    profiles = payload.get("profiles")
    if isinstance(profiles, dict):
        profile = profiles.get(profile_uuid)
        if isinstance(profile, dict):
            return profile
    countries = payload.get("countries")
    if isinstance(countries, dict) and country:
        wanted = country.strip().casefold()
        for key, value in countries.items():
            if str(key).strip().casefold() == wanted and isinstance(value, dict):
                return value
    default = payload.get("default")
    if isinstance(default, dict):
        return default
    return {}
