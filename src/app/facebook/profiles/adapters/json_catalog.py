from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from ..discovery.mapping import profile_from_dict, profile_to_dict
from ..models import Profile

_CATALOG_LOCK = threading.Lock()


class JsonProfileCatalog:
    def __init__(self, path: Path) -> None:
        self._path = path

    def list_profiles(self) -> list[Profile]:
        payload = self._load(default={"profiles": []})
        raw_profiles = (
            payload.get("profiles", []) if isinstance(payload, dict) else payload
        )
        return [
            profile_from_dict(raw)
            for raw in raw_profiles
            if isinstance(raw, dict) and raw.get("octo_profile_uuid")
        ]

    def add_missing(self, profiles: list[Profile]) -> int:
        with _CATALOG_LOCK:
            current = self.list_profiles()
            known = {profile.octo_profile_uuid for profile in current}
            missing: list[Profile] = []
            for profile in profiles:
                if not profile.octo_profile_uuid or profile.octo_profile_uuid in known:
                    continue
                known.add(profile.octo_profile_uuid)
                missing.append(profile)
            if not missing:
                return 0
            current.extend(missing)
            self._write({"profiles": [profile_to_dict(profile) for profile in current]})
            return len(missing)

    def adopt_country(self, profile_uuid: str, country: str) -> bool:
        with _CATALOG_LOCK:
            profiles = self.list_profiles()
            changed = False
            for profile in profiles:
                if profile.octo_profile_uuid != profile_uuid:
                    continue
                if not profile.expected_country:
                    profile.expected_country = country
                    changed = True
                break
            if changed:
                self._write(
                    {"profiles": [profile_to_dict(profile) for profile in profiles]}
                )
            return changed

    def _load(self, *, default: Any) -> Any:
        if not self._path.exists():
            return default
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def _write(self, payload: Any) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self._path)
