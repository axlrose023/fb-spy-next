from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.facebook.adapters import (
    CallbackOctoTransport,
    OctoActiveProfileSource,
    OctoHttpClient,
    OctoProfileSessionManager,
    OctoPublicProfileSource,
)
from app.facebook.orchestration.commands import (
    ActiveDiscoveryCommandHooks,
    PublicDiscoveryCommandRequest,
    RuntimeDiscoveryHooks,
    RuntimeDiscoveryRequest,
    run_active_discovery_command,
    run_public_discovery_command,
    run_runtime_discovery,
)
from app.facebook.profiles import (
    OctoPayloadProfileSource,
    Profile,
    adopt_catalog_country,
    discover_catalog_profiles,
    list_catalog_profiles,
)

from .context import RuntimeContext

PublicPayloadLoader = Callable[[str, str], list[dict[str, Any]]]


def discover_profiles(
    args: Any,
    context: RuntimeContext,
    *,
    fail_fast: bool,
) -> None:
    if not args.discover_octo_profiles:
        return
    settings = context.config.facebook
    run_runtime_discovery(
        RuntimeDiscoveryRequest(
            enabled=args.discover_octo_profiles,
            profiles_path=Path(args.profiles_json),
            cli_token=args.octo_api_token,
            environment_token=os.environ.get("OCTO_API_TOKEN", ""),
            configured_token=settings.octo_api_token,
            cli_search_tags=args.octo_search_tags,
            configured_search_tags=settings.octo_search_tags,
            enable_new=args.enable_discovered,
            fail_fast=fail_fast,
        ),
        RuntimeDiscoveryHooks(
            merge_profiles=lambda path, token, tags, enable: merge_public_profiles(
                path,
                token=token,
                search_tags=tags,
                enable_new=enable,
            ),
            log=context.log,
        ),
    )


def discover_active(args: Any, context: RuntimeContext) -> int:
    profiles_path = Path(args.profiles_json)
    source = OctoActiveProfileSource(
        OctoProfileSessionManager(local_octo_transport(args.octo_host, args.octo_port))
    )
    result: int = run_active_discovery_command(
        enable_new=bool(args.enable_new),
        hooks=ActiveDiscoveryCommandHooks(
            discover=lambda enable_new: discover_catalog_profiles(
                profiles_path,
                source,
                enable_new=enable_new,
            ),
            log=context.log,
        ),
    )
    return result


def discover_public(args: Any, context: RuntimeContext) -> int:
    result: int = run_public_discovery_command(
        PublicDiscoveryCommandRequest(
            profiles_path=Path(args.profiles_json),
            token=args.octo_api_token or os.environ.get("OCTO_API_TOKEN", ""),
            search_tags=args.octo_search_tags,
            enable_new=bool(args.enable_new),
        ),
        RuntimeDiscoveryHooks(
            merge_profiles=lambda path, token, tags, enable: merge_public_profiles(
                path,
                token=token,
                search_tags=tags,
                enable_new=enable,
            ),
            log=context.log,
        ),
    )
    return result


def merge_public_profiles(
    profiles_path: Path,
    *,
    token: str,
    search_tags: str = "",
    enable_new: bool = False,
    payload_loader: PublicPayloadLoader | None = None,
) -> int:
    if not token:
        raise RuntimeError("Octo Public API token is required")
    loader = payload_loader or public_profile_payloads
    source = OctoPayloadProfileSource(lambda tags: loader(token, tags))
    result = discover_catalog_profiles(
        profiles_path,
        source,
        search_tags=search_tags,
        enable_new=enable_new,
    )
    added: int = result.added
    return added


def load_profiles(path: Path) -> list[Profile]:
    profiles: list[Profile] = list_catalog_profiles(path)
    return profiles


def persist_profile_country(path: Path, profile_uuid: str, country: str) -> None:
    adopt_catalog_country(path, profile_uuid, country)


def local_octo_get(host: str, port: int, path: str) -> dict[str, Any] | list[Any]:
    payload: dict[str, Any] | list[Any] = OctoHttpClient(
        f"http://{host}:{port}"
    ).request("GET", path)
    return payload


def local_octo_post(
    host: str,
    port: int,
    path: str,
    body: dict[str, Any],
) -> dict[str, Any] | list[Any]:
    payload: dict[str, Any] | list[Any] = OctoHttpClient(
        f"http://{host}:{port}"
    ).request("POST", path, body)
    return payload


def local_octo_transport(host: str, port: int) -> CallbackOctoTransport:
    return CallbackOctoTransport(
        get=lambda path: local_octo_get(host, port, path),
        post=lambda path, body: local_octo_post(host, port, path, body),
    )


def stop_octo_profile(
    profile: Profile,
    args: Any,
    context: RuntimeContext,
) -> None:
    settings = context.config.facebook
    host = args.octo_host or settings.octo_host
    port = args.octo_port or settings.octo_port
    try:
        sessions = OctoProfileSessionManager(local_octo_transport(host, port))
        if not any(
            active.octo_profile_uuid == profile.octo_profile_uuid
            for active in sessions.active()
        ):
            return
        sessions.stop(profile.octo_profile_uuid)
        context.log(f"[{profile.display_name}] Octo profile stopped")
    except Exception as exc:
        context.log(f"[{profile.display_name}] Octo profile stop failed: {exc!r}")


def public_profile_payloads(
    token: str,
    search_tags: str = "",
) -> list[dict[str, Any]]:
    source = OctoPublicProfileSource(
        OctoHttpClient(
            "https://app.octobrowser.net",
            token=token,
        )
    )
    return [
        {"uuid": profile.octo_profile_uuid, "title": profile.label}
        for profile in source.discover(search_tags=search_tags)
    ]
