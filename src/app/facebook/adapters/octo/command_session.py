from __future__ import annotations

from app.facebook.profiles import ProfileSession

from .mapping import rewrite_cdp_endpoint_host
from .runtime import OctoLocalRuntime


def acquire_command_session(
    *,
    host: str,
    port: int,
    profile_uuid: str,
    headless: bool,
) -> ProfileSession:
    session = OctoLocalRuntime(
        f"http://{host}:{port}",
        profile_uuid,
        headless=headless,
    ).acquire()
    return ProfileSession(
        rewrite_cdp_endpoint_host(session.ws_endpoint, host),
        session.connection,
    )
