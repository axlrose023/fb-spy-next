from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from app.facebook.orchestration.adapters import (
    CollectionProcessCommandFactory,
    OctoProcessEnvironment,
    PythonProcessEnvironment,
    build_backend_import_command,
    build_collector_command,
    build_isolated_landing_resolver_command,
    build_relevance_classifier_command,
    build_relevant_enricher_command,
)
from app.facebook.profiles import Profile
from app.facebook.settings import FacebookConfig

pytestmark = pytest.mark.unit


@dataclass
class PipelineOptions:
    octo_host: str = ""
    octo_port: int = 0
    octo_headless: bool | None = None
    collect_minutes: float = 15
    collect_scrolls: int = 10_000
    resolve_max: int = 200
    scroll_px: int = 520
    max_ads_per_view: int = 1
    landing_archive_timeout: float = 12
    landing_archive_max_resources: int = 80
    video_max_seconds: float = 10
    debug: bool = False
    interest_safe_collection: bool = False
    no_video_recording: bool = False
    no_landing_archives: bool = False
    calibration_page_timeout: float = 45
    calibration_locate_timeout: float = 12
    calibration_landing_timeout: float = 20


def octo_environment(*, headless: bool = False) -> OctoProcessEnvironment:
    return OctoProcessEnvironment(
        executable="python",
        collector_module="collector.module",
        host="127.0.0.1",
        port=58888,
        headless=headless,
    )


def option_value(command: list[str], name: str) -> str:
    return command[command.index(name) + 1]


def test_collector_command_preserves_required_argv_order(tmp_path: Path) -> None:
    command = build_collector_command(
        Profile("profile-uuid"),
        PipelineOptions(),
        tmp_path,
        octo_environment(),
    )

    assert command[:3] == ["python", "-m", "collector.module"]
    assert option_value(command, "--minutes") == "15"
    assert option_value(command, "--octo-profile-uuid") == "profile-uuid"
    assert option_value(command, "--run-dir") == str(tmp_path)
    assert "--passive-collect" not in command
    assert "--octo-headless" not in command


def test_collector_command_adds_enabled_optional_flags(tmp_path: Path) -> None:
    options = PipelineOptions(
        debug=True,
        interest_safe_collection=True,
        no_video_recording=True,
        no_landing_archives=True,
    )

    command = build_collector_command(
        Profile("profile"), options, tmp_path, octo_environment(headless=True)
    )

    assert command[-5:] == [
        "--debug",
        "--passive-collect",
        "--no-video-recording",
        "--no-landing-archives",
        "--octo-headless",
    ]


def test_classifier_command_supports_staged_source_and_video(tmp_path: Path) -> None:
    source = tmp_path / "ads.enriched.json"
    environment = PythonProcessEnvironment("python")

    standard = build_relevance_classifier_command(tmp_path, environment)
    staged = build_relevance_classifier_command(
        tmp_path,
        environment,
        stage="finalize",
        source=source,
        include_video=True,
    )

    assert standard[:3] == ["python", "-m", "app.facebook.relevance.commands"]
    assert "--stage" not in standard
    assert staged[-5:] == [
        "--stage",
        "finalize",
        "--source",
        str(source),
        "--include-video",
    ]


def test_enricher_command_clamps_timeouts_and_adds_guards(tmp_path: Path) -> None:
    options = PipelineOptions(
        calibration_page_timeout=0,
        calibration_locate_timeout=-1,
        no_video_recording=True,
        no_landing_archives=True,
    )
    source = tmp_path / "ads.gated.json"

    command = build_relevant_enricher_command(
        Profile("profile"),
        options,
        tmp_path,
        octo_environment(headless=True),
        source=source,
    )

    assert command[:3] == ["python", "-m", "app.facebook.enrichment.commands"]
    assert option_value(command, "--timeout-ms") == "1"
    assert option_value(command, "--locate-timeout-ms") == "0"
    assert command[-5:] == [
        "--source",
        str(source),
        "--no-record-videos",
        "--no-resolve-landings",
        "--octo-headless",
    ]

    plain = build_relevant_enricher_command(
        Profile("profile"),
        PipelineOptions(),
        tmp_path,
        octo_environment(),
    )
    assert "--source" not in plain
    assert "--no-record-videos" not in plain
    assert "--no-resolve-landings" not in plain
    assert "--octo-headless" not in plain


def test_isolated_resolver_and_backend_import_commands(tmp_path: Path) -> None:
    profile = Profile("profile", label="Spain")
    isolated = build_isolated_landing_resolver_command(
        profile,
        PipelineOptions(calibration_landing_timeout=0),
        tmp_path,
        octo_environment(headless=True),
    )
    ads_path = tmp_path / "collect" / "ads.relevant.json"
    imported = build_backend_import_command(
        profile,
        ads_path,
        PythonProcessEnvironment("python"),
    )

    assert isolated[:3] == [
        "python",
        "-m",
        "app.facebook.relevance.evidence.browser_command",
    ]
    assert option_value(isolated, "--timeout-ms") == "1"
    assert isolated[-1] == "--octo-headless"
    assert imported[:3] == ["python", "-m", "app.facebook.runs.commands"]
    assert option_value(imported, "--ads-json") == str(ads_path)
    assert option_value(imported, "--title") == "Spain - collect"


def test_collection_factory_composes_all_builders_with_runtime_config(
    tmp_path: Path,
) -> None:
    settings = FacebookConfig(
        runner_python="configured-python",
        runner_module="configured.collector",
        octo_host="configured-host",
        octo_port=58888,
        octo_headless=True,
    )
    options = PipelineOptions(
        octo_host="cli-host",
        octo_port=59999,
        octo_headless=False,
    )
    profile = Profile("profile", label="Canada")
    source = tmp_path / "ads.gated.json"
    factory = CollectionProcessCommandFactory(settings)
    octo = OctoProcessEnvironment(
        executable="configured-python",
        collector_module="configured.collector",
        host="cli-host",
        port=59999,
        headless=False,
    )
    python = PythonProcessEnvironment("configured-python")

    assert factory.collector(profile, options, tmp_path) == build_collector_command(
        profile, options, tmp_path, octo
    )
    assert factory.classifier(
        tmp_path,
        stage="finalize",
        source=source,
        include_video=True,
    ) == build_relevance_classifier_command(
        tmp_path,
        python,
        stage="finalize",
        source=source,
        include_video=True,
    )
    assert factory.enricher(
        profile,
        options,
        tmp_path,
        source=source,
    ) == build_relevant_enricher_command(
        profile,
        options,
        tmp_path,
        octo,
        source=source,
    )
    assert factory.isolated_resolver(
        profile, options, tmp_path
    ) == build_isolated_landing_resolver_command(profile, options, tmp_path, octo)
    assert factory.backend_import(profile, source) == build_backend_import_command(
        profile, source, python
    )
