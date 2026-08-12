from __future__ import annotations

import threading
import time
from collections.abc import Callable

from app.facebook.adapters import OctoProfileSessionManager
from app.facebook.profiles import Profile

_OCTO_STOP_LOCK = threading.Lock()


def stop_profile(
    profile: Profile,
    *,
    sessions: OctoProfileSessionManager,
    log: Callable[[str], None],
) -> None:
    with _OCTO_STOP_LOCK:
        try:
            if not _profile_is_active(sessions, profile.octo_profile_uuid):
                return
            sessions.stop(profile.octo_profile_uuid)
        except Exception as exc:
            if _wait_until_inactive(sessions, profile.octo_profile_uuid):
                log(
                    f"[{profile.display_name}] Octo profile stopped "
                    "after transport error"
                )
                return
            log(f"[{profile.display_name}] Octo profile stop failed: {exc!r}")
            return
        log(f"[{profile.display_name}] Octo profile stopped")


def _profile_is_active(
    sessions: OctoProfileSessionManager,
    profile_uuid: str,
) -> bool:
    return any(
        active.octo_profile_uuid == profile_uuid for active in sessions.active()
    )


def _wait_until_inactive(
    sessions: OctoProfileSessionManager,
    profile_uuid: str,
    *,
    attempts: int = 5,
) -> bool:
    for attempt in range(max(1, attempts)):
        try:
            if not _profile_is_active(sessions, profile_uuid):
                return True
        except Exception:
            pass
        if attempt + 1 < attempts:
            time.sleep(1)
    return False
