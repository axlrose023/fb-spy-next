from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ..models import Profile


def profile_from_dict(raw: dict[str, Any]) -> Profile:
    return Profile.from_dict(raw)


def profile_to_dict(profile: Profile) -> dict[str, Any]:
    return asdict(profile)
