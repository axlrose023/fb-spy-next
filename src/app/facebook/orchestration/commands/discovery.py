from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RuntimeDiscoveryRequest:
    enabled: bool
    profiles_path: Path
    cli_token: str
    environment_token: str
    configured_token: str
    cli_search_tags: str
    configured_search_tags: str
    enable_new: bool
    fail_fast: bool


@dataclass(frozen=True, slots=True)
class RuntimeDiscoveryHooks:
    merge_profiles: Callable[[Path, str, str, bool], int]
    log: Callable[[str], None]


def run_runtime_discovery(
    request: RuntimeDiscoveryRequest,
    hooks: RuntimeDiscoveryHooks,
) -> None:
    if not request.enabled:
        return
    token = request.cli_token or request.environment_token or request.configured_token
    search_tags = request.cli_search_tags or request.configured_search_tags
    if not token:
        hooks.log(
            "[orchestrator] Octo Public API discovery skipped: token is not "
            "configured; using profiles.json"
        )
        return
    try:
        added = hooks.merge_profiles(
            request.profiles_path,
            token,
            search_tags,
            request.enable_new,
        )
        if added:
            hooks.log(f"[orchestrator] discovered {added} new Octo profile(s)")
    except Exception as exc:
        if request.fail_fast:
            raise
        hooks.log(f"[orchestrator] Octo discovery failed: {exc!r}")
