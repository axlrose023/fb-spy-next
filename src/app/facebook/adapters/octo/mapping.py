from __future__ import annotations

import re
import socket
from typing import Any

from app.facebook.profiles import (
    ActiveProfile,
    DiscoveredProfile,
    ProfileConnection,
    ProfileSession,
    ProfileSessionError,
    normalize_country,
)


def active_profile_from_raw(raw: dict[str, Any]) -> ActiveProfile | None:
    profile_uuid = str(raw.get("uuid") or "")
    if not profile_uuid:
        return None
    return ActiveProfile(
        octo_profile_uuid=profile_uuid,
        label=str(raw.get("title") or raw.get("name") or profile_uuid[:8]),
        headless=bool(raw.get("headless")),
        ws_endpoint=_clean(raw.get("ws_endpoint")),
        connection=connection_from_raw(raw.get("connection_data")),
    )


def public_profile_from_raw(raw: dict[str, Any]) -> DiscoveredProfile | None:
    profile_uuid = str(raw.get("uuid") or "")
    if not profile_uuid:
        return None
    return DiscoveredProfile(
        octo_profile_uuid=profile_uuid,
        label=str(raw.get("title") or profile_uuid[:8]),
    )


def active_discovery_profile(active: ActiveProfile) -> DiscoveredProfile:
    return DiscoveredProfile(
        octo_profile_uuid=active.octo_profile_uuid,
        label=active.label,
        observed_country=active.connection.country,
    )


def session_from_raw(raw: dict[str, Any]) -> ProfileSession:
    endpoint = _clean(raw.get("ws_endpoint"))
    if endpoint is None:
        raise ProfileSessionError("Octo profile session has no CDP endpoint")
    return ProfileSession(
        ws_endpoint=endpoint,
        connection=connection_from_raw(raw.get("connection_data")),
    )


def connection_from_raw(raw: Any) -> ProfileConnection:
    values = raw if isinstance(raw, dict) else {}
    return ProfileConnection(
        country=normalize_country(_clean(values.get("country"))),
        ip=_clean(values.get("ip")),
    )


def rewrite_cdp_endpoint_host(ws_endpoint: str, octo_host: str) -> str:
    if octo_host in {"127.0.0.1", "localhost"}:
        return ws_endpoint
    match = re.match(r"^(wss?://)([^/:]+)(.*)$", ws_endpoint)
    if not match or match.group(2) not in {"127.0.0.1", "localhost"}:
        return ws_endpoint
    try:
        cdp_host = socket.gethostbyname(octo_host)
    except OSError:
        cdp_host = octo_host
    return f"{match.group(1)}{cdp_host}{match.group(3)}"


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
