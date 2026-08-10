from __future__ import annotations

import json
import signal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.facebook.orchestration.adapters import ProcessRegistry
from app.facebook.orchestration.runtime import RuntimeContext, application, collection
from app.facebook.orchestration.runtime.profiles import merge_public_profiles
from app.facebook.profiles import Profile
from app.settings import Config, MediaStorageConfig

pytestmark = pytest.mark.unit


class RecordingRegistry:
    def __init__(self) -> None:
        self.signals: list[signal.Signals] = []

    def signal_all(self, value: signal.Signals) -> None:
        self.signals.append(value)


def runtime_context() -> tuple[RuntimeContext, RecordingRegistry, list[str]]:
    registry = RecordingRegistry()
    output: list[str] = []
    config = Config(
        media=MediaStorageConfig(
            backend="local",
            signing_secret="test-media-signing-secret-at-least-32-characters",
        )
    )
    context = RuntimeContext(
        config_provider=lambda: config,
        process_registry=cast(ProcessRegistry, registry),
        output=lambda message, _flush: output.append(message),
    )
    return context, registry, output


def test_runtime_stop_request_is_owned_by_explicit_context() -> None:
    context, registry, _output = runtime_context()

    context.request_stop(signal.SIGTERM, None)

    assert context.stop_event.is_set()
    assert registry.signals == [signal.SIGINT]


def test_runtime_cli_dispatches_run_through_canonical_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _registry, _output = runtime_context()
    calls: list[str] = []
    monkeypatch.setattr(signal, "signal", lambda *_args: None)

    def run(args: Any, _context: RuntimeContext) -> int:
        calls.append(str(args.command))
        return 17

    monkeypatch.setattr(application, "run", run)

    result = application.run_cli(["run"], context=context)

    assert result == 17
    assert calls == ["run"]


class NoProcessCommands:
    def __getattr__(self, name: str) -> Any:
        def fail(*_args: Any, **_kwargs: Any) -> None:
            raise AssertionError(f"dry run requested process command: {name}")

        return fail


def test_collection_runtime_dry_run_starts_no_processes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _registry, output = runtime_context()
    monkeypatch.setattr(
        collection,
        "process_commands",
        lambda _context: NoProcessCommands(),
    )
    args = SimpleNamespace(
        dry_run=True,
        interest_safe_collection=True,
        isolated_hold_resolution=True,
        relevant_enrichment=True,
        import_backend=True,
        no_video_recording=False,
        collect_minutes=15,
        collect_timeout_grace=180,
        relevance_timeout=60,
        isolated_resolution_timeout=60,
        enrichment_timeout=60,
        backend_import_timeout=60,
        classify_relevance=True,
    )

    state = collection.run_collection_pipeline(
        Profile(octo_profile_uuid="profile"),
        args,
        tmp_path,
        context,
    )

    assert state.collect_code == 0
    assert state.relevance_code is None
    assert output == []


def test_public_profile_merge_uses_injected_payload_source(tmp_path: Path) -> None:
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text('{"profiles":[]}', encoding="utf-8")

    added = merge_public_profiles(
        profiles_path,
        token="redacted",
        search_tags="facebook",
        enable_new=True,
        payload_loader=lambda token, tags: [
            {
                "uuid": f"{token}-profile",
                "title": tags,
            }
        ],
    )

    assert added == 1
    assert "redacted-profile" in profiles_path.read_text(encoding="utf-8")


def test_runtime_cli_completes_integrated_profile_dry_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, _registry, output = runtime_context()
    monkeypatch.setattr(signal, "signal", lambda *_args: None)
    profiles_path = tmp_path / "profiles.json"
    state_path = tmp_path / "state.json"
    root_dir = tmp_path / "runs"
    profiles_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "octo_profile_uuid": "profile",
                        "label": "Canada",
                        "expected_country": "Canada",
                        "enabled": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = application.run_cli(
        [
            "run",
            "--profiles-json",
            str(profiles_path),
            "--state-json",
            str(state_path),
            "--root-dir",
            str(root_dir),
            "--dry-run",
            "--max-parallel",
            "1",
        ],
        context=context,
    )

    assert result == 0
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert set(state["profiles"]) == {"profile"}
    assert any("collect ->" in message for message in output)
