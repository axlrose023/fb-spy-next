from __future__ import annotations

from pathlib import Path

import pytest

from app.facebook.orchestration.commands import (
    ActiveDiscoveryCommandHooks,
    PublicDiscoveryCommandRequest,
    RuntimeDiscoveryHooks,
    RuntimeDiscoveryRequest,
    run_active_discovery_command,
    run_public_discovery_command,
    run_runtime_discovery,
)
from app.facebook.profiles import DiscoveryResult

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("cli_token", "environment_token", "configured_token", "expected_token"),
    [
        ("cli", "environment", "configured", "cli"),
        ("", "environment", "configured", "environment"),
        ("", "", "configured", "configured"),
    ],
)
def test_runtime_discovery_uses_token_precedence_and_configured_tags(
    tmp_path: Path,
    cli_token: str,
    environment_token: str,
    configured_token: str,
    expected_token: str,
) -> None:
    merges: list[tuple[Path, str, str, bool]] = []
    logs: list[str] = []
    profiles_path = tmp_path / "profiles.json"

    def merge_profiles(path: Path, token: str, tags: str, enable: bool) -> int:
        merges.append((path, token, tags, enable))
        return 2

    run_runtime_discovery(
        _request(
            profiles_path,
            cli_token=cli_token,
            environment_token=environment_token,
            configured_token=configured_token,
            cli_search_tags="",
            configured_search_tags="facebook",
        ),
        RuntimeDiscoveryHooks(merge_profiles=merge_profiles, log=logs.append),
    )

    assert merges == [(profiles_path, expected_token, "facebook", True)]
    assert logs == ["[orchestrator] discovered 2 new Octo profile(s)"]


def test_runtime_discovery_skips_disabled_and_missing_token(tmp_path: Path) -> None:
    merges: list[str] = []
    logs: list[str] = []

    def merge_profiles(*_args: object) -> int:
        merges.append("merge")
        return 0

    hooks = RuntimeDiscoveryHooks(
        merge_profiles=merge_profiles,
        log=logs.append,
    )

    run_runtime_discovery(
        _request(tmp_path / "disabled.json", enabled=False, cli_token="token"),
        hooks,
    )
    run_runtime_discovery(_request(tmp_path / "missing.json"), hooks)

    assert merges == []
    assert logs == [
        "[orchestrator] Octo Public API discovery skipped: token is not "
        "configured; using profiles.json"
    ]


@pytest.mark.parametrize("fail_fast", [False, True])
def test_runtime_discovery_respects_failure_mode(
    tmp_path: Path,
    fail_fast: bool,
) -> None:
    logs: list[str] = []

    def fail_merge(*_args: object) -> int:
        raise RuntimeError("Octo unavailable")

    request = _request(
        tmp_path / "profiles.json",
        cli_token="token",
        fail_fast=fail_fast,
    )
    hooks = RuntimeDiscoveryHooks(merge_profiles=fail_merge, log=logs.append)

    if fail_fast:
        with pytest.raises(RuntimeError, match="Octo unavailable"):
            run_runtime_discovery(request, hooks)
        assert logs == []
    else:
        run_runtime_discovery(request, hooks)
        assert logs == [
            "[orchestrator] Octo discovery failed: RuntimeError('Octo unavailable')"
        ]


def test_active_discovery_command_reports_result() -> None:
    enabled: list[bool] = []
    logs: list[str] = []

    def discover(enable_new: bool) -> DiscoveryResult:
        enabled.append(enable_new)
        return DiscoveryResult(discovered=5, added=2)

    result = run_active_discovery_command(
        enable_new=True,
        hooks=ActiveDiscoveryCommandHooks(discover=discover, log=logs.append),
    )

    assert result == 0
    assert enabled == [True]
    assert logs == ["active=5 added=2"]


def test_public_discovery_command_reports_added_without_token_log(
    tmp_path: Path,
) -> None:
    merges: list[tuple[Path, str, str, bool]] = []
    logs: list[str] = []
    profiles_path = tmp_path / "profiles.json"

    def merge_profiles(path: Path, token: str, tags: str, enable: bool) -> int:
        merges.append((path, token, tags, enable))
        return 3

    result = run_public_discovery_command(
        PublicDiscoveryCommandRequest(
            profiles_path=profiles_path,
            token="secret-token",
            search_tags="facebook",
            enable_new=False,
        ),
        RuntimeDiscoveryHooks(merge_profiles=merge_profiles, log=logs.append),
    )

    assert result == 0
    assert merges == [(profiles_path, "secret-token", "facebook", False)]
    assert logs == ["added=3"]


def _request(
    profiles_path: Path,
    *,
    enabled: bool = True,
    cli_token: str = "",
    environment_token: str = "",
    configured_token: str = "",
    cli_search_tags: str = "tag",
    configured_search_tags: str = "configured-tag",
    fail_fast: bool = False,
) -> RuntimeDiscoveryRequest:
    return RuntimeDiscoveryRequest(
        enabled=enabled,
        profiles_path=profiles_path,
        cli_token=cli_token,
        environment_token=environment_token,
        configured_token=configured_token,
        cli_search_tags=cli_search_tags,
        configured_search_tags=configured_search_tags,
        enable_new=True,
        fail_fast=fail_fast,
    )
